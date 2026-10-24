#!/usr/bin/env bash
# Prueba REAL de la logica SECRET_KEY de start.sh (sin ejecutar la app).
# Extrae el bloque de funciones y lo ejerce en un sandbox.
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || exit 1

FALLOS=0
check() {
    local nombre="$1"; local cond="$2"; local detalle="${3:-}"
    if [[ "$cond" == "1" ]]; then
        echo "PASA $nombre ${detalle:+:: $detalle}"
    else
        echo "FALLA $nombre ${detalle:+:: $detalle}"
        FALLOS=$((FALLOS+1))
    fi
}

# --- Extraer el bloque de funciones SECRET_KEY -------------------------------
# Del comentario "# 0) SECRET_KEY" hasta la linea "_asegurar_secret_key"
awk '/^# 0\) SECRET_KEY/,/^_asegurar_secret_key$/' start.sh > /tmp/sk_funcs.sh
if ! grep -q "_asegurar_secret_key()" /tmp/sk_funcs.sh; then
    echo "FALLA no se pudo extraer el bloque de funciones"
    exit 1
fi
# shellcheck disable=SC1091
source /tmp/sk_funcs.sh

SANDBOX="/tmp/grm_sk_test_$$"
rm -rf "$SANDBOX"; mkdir -p "$SANDBOX"
export SECRET_KEY_FILE="$SANDBOX/secret_key"
export HOME="$SANDBOX/home"; mkdir -p "$HOME"

# --- T1: entorno sin clave -> genera y persiste ----------------------------
unset SECRET_KEY
_asegurar_secret_key >/tmp/sk_out1 2>&1
RC1=$?
CLAVE1="${SECRET_KEY:-}"
check "T1: con entorno vacio se genera una clave" "$([[ ${#CLAVE1} -ge 32 ]] && echo 1 || echo 0)" "len=${#CLAVE1} rc=$RC1"
check "T1: la clave se persistio" "$([[ -f "$SECRET_KEY_FILE" ]] && echo 1 || echo 0)" "$SECRET_KEY_FILE"
check "T1: el codigo de salida es 0" "$([[ $RC1 -eq 0 ]] && echo 1 || echo 0)" "rc=$RC1"
check "T1: la clave NO aparece en el log" "$(grep -qF "$CLAVE1" /tmp/sk_out1 && echo 0 || echo 1)" "log=$(head -c 120 /tmp/sk_out1)"

# --- T2: segunda ejecucion -> MISMA clave (idempotencia) --------------------
unset SECRET_KEY
_asegurar_secret_key >/tmp/sk_out2 2>&1
CLAVE2="${SECRET_KEY:-}"
check "T2: la 2da ejecucion reusa la clave persistida (idempotente)" \
      "$([[ -n "$CLAVE2" && "$CLAVE2" == "$CLAVE1" ]] && echo 1 || echo 0)" \
      "igual=$([[ "$CLAVE2" == "$CLAVE1" ]] && echo si || echo no)"

# --- T3: placeholder en el entorno -> se ignora y se usa la persistida ------
SECRET_KEY="change-me-please-in-production"
_asegurar_secret_key >/tmp/sk_out3 2>&1
CLAVE3="${SECRET_KEY:-}"
check "T3: un placeholder en el entorno se reemplaza por la clave persistida" \
      "$([[ "$CLAVE3" == "$CLAVE1" ]] && echo 1 || echo 0)" "len=${#CLAVE3}"

# --- T4: clave valida en el entorno -> se respeta, no se sobrescribe -------
export SECRET_KEY="clave-de-entorno-valida-0123456789abcdef"
_asegurar_secret_key >/tmp/sk_out4 2>&1
check "T4: una clave valida del entorno se respeta" \
      "$([[ "$SECRET_KEY" == "clave-de-entorno-valida-0123456789abcdef" ]] && echo 1 || echo 0)" \
      "SECRET_KEY=$SECRET_KEY"

# --- T5: no persistible -> AVISA pero NO aborta (no hay outage) -----------
SECRET_KEY_FILE="/proc/no-puede-escribir/secreto"
export HOME="/proc/no-puede-escribir/home"
unset SECRET_KEY
_asegurar_secret_key >/tmp/sk_out5 2>&1
RC5=$?
CLAVE5="${SECRET_KEY:-}"
check "T5: sin persistencia NO se aborta (la app arranca)" "$([[ $RC5 -eq 0 ]] && echo 1 || echo 0)" "rc=$RC5"
check "T5: aun asi se usa una clave segura generada" "$([[ ${#CLAVE5} -ge 32 ]] && echo 1 || echo 0)" "len=${#CLAVE5}"
check "T5: se emite un AVISO de persistencia" \
      "$(grep -qi 'no se pudo persistir' /tmp/sk_out5 && echo 1 || echo 0)" \
      "log=$(grep -i 'no se pudo persistir' /tmp/sk_out5 | head -1)"
check "T5: la clave NO aparece en el log" "$(grep -qF "$CLAVE5" /tmp/sk_out5 && echo 0 || echo 1)"

# --- T6: deteccion de placeholders -----------------------------------------
for mal in "change-me" "CHANGEME" "change_me" "secret" "dev-secret" "placeholder" "your-secret-key" ""; do
    if _secret_key_insegura "$mal"; then r="detectada"; else r="NO detectada"; fi
    check "T6: placeholder '$mal' se marca como insegura" "$([[ "$r" == "detectada" ]] && echo 1 || echo 0)" "$r"
done
for bien in "a1b2c3d4e5f6" "x" "clave-larga-y-aleatoria-0123456789"; do
    if _secret_key_insegura "$bien"; then r="marcada insegura"; else r="aceptada"; fi
    check "T6: clave '$bien' se acepta" "$([[ "$r" == "aceptada" ]] && echo 1 || echo 0)" "$r"
done

# --- T7: la clave persistida no queda legible para otros (permisos) --------
# NOTA DE PLATAFORMA: en este sandbox (Windows + Git Bash sobre NTFS) el
# comando `chmod` es un no-op: el filesystem NTFS no representa el bit POSIX
# de otros-lectura. Se verifica con un experimento control en _ctrl_perm.sh
# ("antes" y "despues" de `chmod 600` son identicos: -rw-r--r--). Por eso
# aqui NO se puede comprobar el modo 600; lo que se comprueba es que la
# llamada `chmod 600` esta presente en el codigo y que el archivo se creo.
export SECRET_KEY_FILE="$SANDBOX/perm/secret_key"
mkdir -p "$SANDBOX/perm"
unset SECRET_KEY
_asegurar_secret_key >/dev/null 2>&1
PERM=$(ls -l "$SECRET_KEY_FILE" 2>/dev/null | cut -c1-10)
check "T7: el archivo persistido se creo" \
      "$([[ -f "$SECRET_KEY_FILE" ]] && echo 1 || echo 0)" "ruta=$SECRET_KEY_FILE"
if [[ "$PERM" == "-rw-------" ]]; then
    check "T7: permisos 600 aplicados" 1 "perm=$PERM"
else
    echo "INFO T7: permisos 600 NO verificables en este sandbox (NTFS, chmod es no-op);"
    echo "INFO T7: en Linux el 'chmod 600' de start.sh si aplica. Ver _ctrl_perm.sh."
fi
# El codigo debe contener la llamada chmod 600.
if grep -q "chmod 600" start.sh; then
    check "T7: start.sh contiene la llamada 'chmod 600'" 1 "encontrada en start.sh"
else
    check "T7: start.sh contiene la llamada 'chmod 600'" 0 "NO encontrada"
fi

rm -rf "$SANDBOX" /tmp/sk_funcs.sh /tmp/sk_out1 /tmp/sk_out2 /tmp/sk_out3 /tmp/sk_out4 /tmp/sk_out5

echo ""
if [[ $FALLOS -eq 0 ]]; then
    echo "RESULTADO START.SH SECRET_KEY: todas las comprobaciones superadas"
    exit 0
fi
echo "RESULTADO START.SH SECRET_KEY: $FALLOS FALLOS"
exit 1
