"""
Configuración central de la aplicación.
Soporta modo desarrollo (SQLite) y producción (PostgreSQL/Redis) vía variables de entorno.
"""
import json
import logging
import os
from functools import lru_cache
from typing import List
from urllib.parse import urlsplit, urlunsplit
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# Defaults de Celery. Se usan como sentinel para saber si el valor actual
# viene del entorno (o de un .env) o es simply el default de la clase.
_CELERY_BROKER_DEFAULT = "redis://localhost:6379/1"
_CELERY_BACKEND_DEFAULT = "redis://localhost:6379/2"


def _redis_url_con_db(url: str, db: int) -> str:
    """Devuelve la URL de Redis apuntando a la base de datos ``db``.

    Conserva esquema, credenciales, host, puerto y query. Si la URL no se
    puede parsear se devuelve tal cual (no se inventa nada).
    """
    if not url:
        return url
    try:
        partes = urlsplit(url)
    except ValueError:
        return url
    if not partes.scheme or not partes.netloc:
        # URL sin esquema (p. ej. "host:6379"): no se puede reescribir de
        # forma segura, se deja intacta.
        return url
    return urlunsplit(
        (partes.scheme, partes.netloc, f"/{db}", partes.query, partes.fragment)
    )


class Settings(BaseSettings):
    """Configuración de la aplicación cargada desde .env o variables de entorno."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # === Aplicación ===
    APP_NAME: str = "Bitácora GRM"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True
    # Sin default hardcodeado: si la clave no está definida en el entorno
    # queda vacía y ``es_secreto_inseguro()``/``validar()`` lo detectan.
    # Nunca reintroducir una clave fija en el repo: con ella, cualquier JWT
    # de cualquier instalación quedaba firmado con una clave pública.
    SECRET_KEY: str = ""

    # === Base de datos ===
    # Si se define DATABASE_URL, se usa directamente. Si no, se construye.
    DATABASE_URL: str = "sqlite:///./bitacora_grm.db"

    # USE_SQLITE=true fuerza SQLite (modo dev/demo). Ahora es un campo de
    # Settings, por lo que pydantic-settings lo lee del .env (antes se
    # consultaba con os.getenv, que nunca veía el .env y por tanto la
    # variable del .env se ignoraba silenciosamente).
    USE_SQLITE: bool = False

    # AUTO_INIT_DB=true corre ``python -m app.db.init_db`` al arrancar.
    # También pasa a ser campo de Settings: app/main.py debe consumirlo como
    # ``settings.AUTO_INIT_DB`` en lugar de os.getenv (no se modifica aquí).
    AUTO_INIT_DB: bool = False

    # Configuración individual (usada para construir DATABASE_URL si no se define)
    POSTGRES_USER: str = "grm"
    POSTGRES_PASSWORD: str = "grm"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "bitacora_grm"

    # === Redis / Celery ===
    # ``REDIS_URL`` es lo único que Railway inyecta al adjuntar el plugin de
    # Redis. ``CELERY_BROKER_URL`` y ``CELERY_RESULT_BACKEND`` se derivan
    # automáticamente de ``REDIS_URL`` (bases 1 y 2) cuando no se definen de
    # forma explícita: ver ``_derivar_urls_celery``. Sin ese derivado, un
    # servicio worker/beat desplegado en Railway publicaba contra
    # ``redis://localhost:6379`` (el default local) y fallaba al encolar.
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = _CELERY_BROKER_DEFAULT
    CELERY_RESULT_BACKEND: str = _CELERY_BACKEND_DEFAULT

    # === Autenticación ===
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_MINUTES: int = 60 * 8

    # === ITSM / Reglas de Negocio ===
    # Roles disponibles en el sistema
    ROLES_DISPONIBLES: List[str] = [
        "administrador",
        "agente_senior",
        "agente",
        "solicitante",
        "observador",
    ]

    # === CORS ===
    CORS_ORIGINS: List[str] = ["*"]

    # ------------------------------------------------------------------
    # Normalización de listas definidas en el entorno
    # ------------------------------------------------------------------
    @field_validator("ROLES_DISPONIBLES", "CORS_ORIGINS", mode="before")
    @classmethod
    def _normalizar_lista(cls, valor):
        """Acepta listas del entorno en formato JSON **o** CSV.

        ``pydantic-settings`` sólo sabe interpretar JSON cuando el campo es
        de tipo complejo (``List[str]``). Si el despliegue define

            CORS_ORIGINS=https://a.example,https://b.example

        (formato CSV, muy habitual al configurar una plataforma de
        despliegue), la aplicación abortaba al arrancar con::

            SettingsError: error parsing value for field "CORS_ORIGINS"

        Lo mismo ocurría con los procesos hijos (Celery worker, scripts) que
        heredaban del proceso padre una lista exportada en CSV.

        Con este validador se aceptan ambas formas:
          * JSON → ``["https://a.example", "https://b.example"]``
          * CSV  → ``https://a.example,https://b.example``
        """
        if valor is None:
            return []
        if isinstance(valor, (list, tuple, set)):
            return list(valor)
        if isinstance(valor, str):
            texto = valor.strip()
            if not texto:
                return []
            if texto.startswith("["):
                try:
                    datos = json.loads(texto)
                except (json.JSONDecodeError, ValueError):
                    datos = None
                if isinstance(datos, list):
                    return [str(v) for v in datos]
            return [p.strip() for p in texto.split(",") if p.strip()]
        return valor

    # === Zona horaria operativa ===
    # Zona horaria usada para mostrar fechas al usuario. La BD siempre
    # almacena en UTC (naive, por compatibilidad con SQLite/PG); los
    # timestamps que se renderizan en HTML o se devuelven al frontend
    # se convierten a esta zona. Por defecto Chile continental, que
    # alterna entre UTC-3 (invierno) y UTC-4 (verano) y resuelve
    # automáticamente el cambio con ``zoneinfo``.
    APP_TIMEZONE: str = "America/Santiago"

    # === SMTP (envío de correos) ===
    # Si SMTP_HOST y SMTP_FROM están definidos, los correos se envían
    # vía SMTP real. Si no, se persisten en tmp/app.email.log (modo dev).
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True
    # SMTP_USE_SSL=True fuerza SMTPS (TLS implícito, típico puerto 465).
    # Si se deja vacío/vacío, se autodetecta: puerto 465 → SSL, resto → STARTTLS.
    SMTP_USE_SSL: bool = False

    # === URL pública del sistema (para los correos) ===
    PUBLIC_BASE_URL: str = "http://localhost:8000"

    # === Backups de Base de Datos ===
    # Directorio donde se almacenan los archivos de backup (se crea si no existe).
    # En Railway es filesystem efímero, por lo que se recomienda apuntar a un
    # volumen persistente o a un servicio externo (S3, GCS) en producción.
    BACKUP_DIR: str = "backups"
    # Política de retención: cantidad de días que se conservan los backups.
    # Los backups más antiguos se eliminan automáticamente al finalizar el job diario.
    BACKUP_RETENTION_DAYS: int = 30
    # Hora del backup diario programado (formato 24h, hora local del Beat worker).
    # Por defecto 00:00 como pidió el usuario.
    BACKUP_DAILY_HOUR: int = 0
    BACKUP_DAILY_MINUTE: int = 0
    # Tamaño máximo permitido por archivo de backup en MB (protección anti-OOM).
    BACKUP_MAX_SIZE_MB: int = 2048

    # === Reporte diario de entregas ===
    # Hora (UTC) en la que Beat dispara la tarea ``generar_reporte_diario``.
    # Por defecto 18:00 UTC (≈ 15:00 hora Chile continental en invierno,
    # 14:00 en horario de verano). El admin puede cambiarlo desde la UI
    # ``/admin/reporte-entregas`` o definiendo estas env vars en Railway.
    REPORTE_ENTREGAS_HOUR: int = 18
    REPORTE_ENTREGAS_MINUTE: int = 0
    # Si False, la tarea programada registra entregas pero NO envía el
    # correo (útil para auditorías o para detener temporalmente el
    # envío mientras se ajusta la plantilla). El admin puede togglearlo
    # desde la UI.
    REPORTE_ENTREGAS_HABILITADO: bool = True

    # ------------------------------------------------------------------
    # Derivación de las URLs de Celery a partir de REDIS_URL
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _derivar_urls_celery(self) -> "Settings":
        """Deriva broker/backend de Celery desde ``REDIS_URL`` si no se definieron.

        Railway sólo inyecta ``REDIS_URL`` al adjuntar el plugin de Redis; los
        campos ``CELERY_BROKER_URL`` / ``CELERY_RESULT_BACKEND`` defaults a
        ``localhost``. Sin este derivado, los servicios *worker* y *beat*
        intentaban publicar contra ``redis://localhost:6379/1`` y fallaban con
        ``ConnectionError`` nada más arrancar.

        Sólo se deriva cuando el valor NO viene del entorno: se respeta
        siempre la configuración explícita (panel de Railway o ``.env``).
        """
        broker_explicito = (
            "CELERY_BROKER_URL" in os.environ
            or self.CELERY_BROKER_URL != _CELERY_BROKER_DEFAULT
        )
        backend_explicito = (
            "CELERY_RESULT_BACKEND" in os.environ
            or self.CELERY_RESULT_BACKEND != _CELERY_BACKEND_DEFAULT
        )
        if not broker_explicito:
            self.CELERY_BROKER_URL = _redis_url_con_db(self.REDIS_URL, 1)
        if not backend_explicito:
            self.CELERY_RESULT_BACKEND = _redis_url_con_db(self.REDIS_URL, 2)
        return self

    def get_database_url(self) -> str:
        """Devuelve la URL de BD; si no se configuró, construye la de PostgreSQL."""
        if self.DATABASE_URL and self.DATABASE_URL != "sqlite:///./bitacora_grm.db":
            return self.DATABASE_URL
        # Si se solicita SQLite explícitamente (leído del .env por
        # pydantic-settings; antes se usaba os.getenv, que nunca veía el .env)
        if self.USE_SQLITE:
            return "sqlite:///./bitacora_grm.db"
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    def get_database_url_enmascarada(self) -> str:
        """URL de la BD con la contraseña oculta. Para logs y respuestas HTTP.

        Sin esto, ``init_database()`` imprimía la URL completa en el log de
        arranque de producción, dejando la contraseña de PostgreSQL a la
        vista de cualquiera con acceso a los logs del despliegue.
        """
        url = self.get_database_url()
        esquema, sep, resto = url.partition("://")
        if not sep or "@" not in resto:
            return url
        credenciales, _, servidor = resto.partition("@")
        if ":" in credenciales:
            usuario = credenciales.split(":", 1)[0]
            credenciales = f"{usuario}:***"
        else:
            credenciales = "***"
        return f"{esquema}://{credenciales}@{servidor}"

    # ------------------------------------------------------------------
    # Validación de configuración (informativa, no bloqueante)
    # ------------------------------------------------------------------
    def es_secreto_inseguro(self) -> bool:
        """True si el SECRET_KEY actual está vacío o es un placeholder del repo.

        El default anterior era "change-me-in-production-please", es decir, una
        clave pública del repositorio con la que quedaban firmados todos los
        JWT de cualquier instalación. El default ahora es "" y esta señal
        permite que el arranque detecte el caso inseguro.
        """
        clave = (self.SECRET_KEY or "").strip()
        if not clave:
            return True
        return "change-me" in clave.lower()

    def _cors_explicitamente_configurado(self) -> bool:
        """True si ``CORS_ORIGINS`` viene del entorno o del ``.env``.

        Distingue el comodín configurado a propósito (un descuido) del valor
        por defecto de la clase (``["*"]``), que es el que usa el arranque
        local sin ``.env``. Se apoya en la marca global
        ``_CORS_ORIGINS_EXPLICITO``, calculada antes de que
        ``_exportar_a_environ`` vuelque los defaults al entorno.
        """
        return _CORS_ORIGINS_EXPLICITO

    @field_validator("PUBLIC_BASE_URL", mode="after")
    @classmethod
    def _derivar_public_base_url(cls, valor: str) -> str:
        """Deriva ``PUBLIC_BASE_URL`` de las variables que Railway inyecta.

        Por qué hace falta
        -----------------
        ``validar()`` aborta el arranque en producción si ``PUBLIC_BASE_URL``
        no usa HTTPS. El default de la clase es ``http://localhost:8000``,
        así que un despliegue en Railway que no defina la variable a mano
        queda con HTTP y el guard aborta la aplicación entera (502 en todas
        las rutas) aunque todo lo demás esté correcto.

        Railway expone automáticamente ``RAILWAY_PUBLIC_DOMAIN`` (y
        ``RAILWAY_STATIC_URL``) en cada servicio. Derivando de ahí se obtiene
        una URL HTTPS correcta **sin relajar el guard**: la comprobación
        sigue exigiendo HTTPS, pero el valor ya llega en HTTPS.

        Reglas
        ------
        * Si el valor ya es HTTPS se respeta tal cual.
        * Si ``PUBLIC_BASE_URL`` fue configurada explícitamente (entorno o
          ``.env``) NO se toca: si alguien la puso en HTTP a propósito, el
          guard debe seguir avisando y abortando.
        * Sólo se derivan variables del proveedor (``RAILWAY_*``): fuera de
          ese entorno el valor por defecto se mantiene intacto.
        """
        actual = (valor or "").strip()
        if actual.startswith("https://"):
            return actual

        if _public_base_url_configurado_explicitamente():
            return actual

        for clave in ("RAILWAY_PUBLIC_DOMAIN", "RAILWAY_STATIC_URL"):
            bruto = (os.environ.get(clave) or "").strip()
            if not bruto:
                continue
            # ``RAILWAY_STATIC_URL`` puede venir como URL completa; en los
            # dos casos se normaliza a https:// sin barra final.
            derivado = bruto.rstrip("/")
            if "://" in derivado:
                if not derivado.startswith("https://"):
                    continue
            else:
                derivado = "https://" + derivado
            logger.info(
                "[config] PUBLIC_BASE_URL derivado de %s: %s", clave, derivado
            )
            return derivado

        return actual

    def _advertir_cors_comodin(self) -> None:
        """Registra el aviso NO bloqueante por ``CORS_ORIGINS=['*']``.

        Por qué el comodín NO es explotable con credenciales en este código:

        * ``app/main.py`` construye el middleware con
          ``allow_credentials=not _cors_wildcard``: con el comodín las
          credenciales quedan **desactivadas**.
        * Starlette, con ``allow_origins=['*']`` y ``allow_credentials=False``,
          responde ``Access-Control-Allow-Origin: *`` y **no** emite
          ``Access-Control-Allow-Credentials``. El navegador, por tanto, no
          adjunta cookies ni credenciales en las peticiones cross-origin: no
          hay lectura de respuestas autenticadas (ni CSRF vía CORS).
        * El riesgo residual queda acotado a orígenes cruzados **sin**
          credenciales (endpoints públicos) y se cierra definiendo los
          orígenes reales en ``CORS_ORIGINS``.
        """
        logger.warning(
            "[cors] CORS_ORIGINS contiene '*' con DEBUG=False: se continúa el "
            "arranque con advertencia (no es bloqueante). El middleware "
            "desactiva allow_credentials ante el comodín "
            "(allow_credentials=not _cors_wildcard en app/main.py), por lo que "
            "el navegador no envía cookies ni credenciales en las peticiones "
            "cross-origin y no hay exfiltración de sesión vía CORS. El riesgo "
            "residual queda acotado a orígenes sin credenciales. "
            "Recomendación: define CORS_ORIGINS con los orígenes reales "
            "(PUBLIC_BASE_URL / dashboard)."
        )

    def validar(self) -> list[str]:
        """Devuelve la lista de avisos de configuración insegura.

        SOLO informa: no lanza excepciones ni muta el estado, de modo que la
        aplicación puede seguir arrancando en desarrollo.

        La validación efectiva (abortar el arranque) corresponde al lifespan de
        ``app/main.py`` (archivo que no se modifica aquí). Integración
        recomendada::

            avisos = settings.validar()
            if avisos and not settings.DEBUG:
                raise RuntimeError(
                    "Configuración insegura:\\n" + "\\n".join(avisos)
                )

        En producción (DEBUG=False) la aplicación DEBE abortar si hay avisos;
        en desarrollo los avisos son únicamente informativos.

        Excepciones a ese contrato:

        * ``CORS_ORIGINS`` con ``'*'`` y ``DEBUG=False`` **no** es bloqueante:
          se degrada a advertencia (ver ``_advertir_cors_comodin``) porque el
          middleware desactiva ``allow_credentials`` ante el comodín y, por
          tanto, no es explotable con credenciales.
        * ``CORS_ORIGINS`` con ``'*'`` explícito y ``DEBUG=True`` **sí** es
          bloqueante: en desarrollo el comodín es un descuido de configuración
          (la app es server-rendered y same-origin, no necesita ``"*"``) y se
          aborta aquí, porque ``app/main.py`` sólo aborta cuando
          ``DEBUG=False``.
        """
        avisos: list[str] = []

        if self.es_secreto_inseguro():
            avisos.append(
                "SECRET_KEY vacía o con valor placeholder ('change-me'): "
                "define una clave aleatoria fuerte (p. ej. `openssl rand -hex 32`)."
            )

        origenes = list(self.CORS_ORIGINS or [])
        comodin = "*" in origenes

        if self.DEBUG:
            if comodin and self._cors_explicitamente_configurado():
                raise RuntimeError(
                    "Configuración insegura:\n"
                    "  - CORS_ORIGINS contiene '*' con DEBUG=True: define los "
                    "orígenes explícitos en desarrollo (p. ej. "
                    "http://localhost:8000)."
                )
        else:
            if comodin:
                # Degradado a advertencia: con el comodín el middleware
                # desactiva allow_credentials, así que no es explotable con
                # credenciales (ver _advertir_cors_comodin).
                self._advertir_cors_comodin()
            if not origenes:
                avisos.append(
                    "CORS_ORIGINS está vacío con DEBUG=False: "
                    "configura los orígenes permitidos en producción."
                )
            if self.PUBLIC_BASE_URL and not self.PUBLIC_BASE_URL.startswith("https://"):
                avisos.append(
                    "PUBLIC_BASE_URL no usa HTTPS con DEBUG=False: "
                    "los enlaces de los correos viajarían sin cifrar."
                )

        return avisos


@lru_cache
def get_settings() -> Settings:
    """Singleton de configuración."""
    return Settings()


def _leer_env_file(ruta) -> dict:
    """Lee un archivo ``.env`` simple y devuelve ``{CLAVE: valor}``.

    Parser mínimo (no es un ``python-dotenv`` completo): soporta líneas
    comentadas, ``export KEY=valor``, comillas simples/dobles y valores con
    ``=`` dentro. Es suficiente para los archivos ``.env`` del proyecto.
    """
    valores: dict = {}
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.strip()
                if not linea or linea.startswith("#"):
                    continue
                if linea.startswith("export "):
                    linea = linea[len("export "):].lstrip()
                if "=" not in linea:
                    continue
                clave, _, valor = linea.partition("=")
                clave = clave.strip()
                valor = valor.strip()
                if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ("'", '"'):
                    valor = valor[1:-1]
                if clave:
                    valores[clave] = valor
    except OSError:
        pass
    return valores


def _public_base_url_configurado_explicitamente() -> bool:
    """True si ``PUBLIC_BASE_URL`` fue fijada a mano (entorno real o ``.env``).

    Se usa para decidir si el valor puede derivarse de las variables del
    proveedor (``RAILWAY_PUBLIC_DOMAIN``). Si la variable fue configurada
    explícitamente, el guard de HTTPS debe seguir evaluando **ese** valor
    tal cual (y abortar si no es HTTPS); nunca se sobrescribe la
    configuración deliberada del despliegue.
    """
    if "PUBLIC_BASE_URL" in os.environ:
        return True
    env_file = Settings.model_config.get("env_file")
    if isinstance(env_file, (list, tuple)):
        env_file = env_file[0] if env_file else None
    if not env_file:
        return False
    return "PUBLIC_BASE_URL" in _leer_env_file(env_file)


# Campos de ``Settings`` cuyo tipo es ``List[str]``.
_CAMPOS_LISTA = ("ROLES_DISPONIBLES", "CORS_ORIGINS")


def _normalizar_lista(texto: str) -> str:
    """Convierte un texto de lista (CSV o JSON) en JSON canónico.

    ``pydantic-settings`` decodifica los campos ``List[str]`` con
    ``json.loads``. Si la variable llega en CSV, la aplicación aborta al
    arrancar con::

        SettingsError: error parsing value for field "CORS_ORIGINS"

    Acepta indistintamente:

    * ``https://a.example,https://b.example`` → ``["https://a.example", "https://b.example"]``
    * ``["https://a.example"]``                → ``["https://a.example"]``
    """
    limpio = (texto or "").strip()
    if not limpio:
        return "[]"
    if limpio.startswith("["):
        try:
            datos = json.loads(limpio)
        except (json.JSONDecodeError, ValueError):
            datos = None
        if isinstance(datos, list):
            return json.dumps([str(d) for d in datos], ensure_ascii=False)
        # JSON mal formado (p. ej. comillas escapadas): se intenta recuperar
        # el contenido interior en lugar de devolver un único elemento basura.
        interior = limpio.strip("[]").strip()
        if interior:
            partes = [p.strip().strip('"').strip("'") for p in interior.split(",")]
            partes = [p for p in partes if p]
            if partes:
                return json.dumps(partes, ensure_ascii=False)
    return json.dumps(
        [p.strip() for p in limpio.split(",") if p.strip()], ensure_ascii=False
    )


def _preparar_listas_del_entorno() -> None:
    """Normaliza a JSON las variables de lista ANTES de construir ``Settings``.

    Se normalizan dos orígenes:

    1. El entorno real (Railway, Docker, CI, shell). Una variable como
       ``CORS_ORIGINS=https://a.example,https://b.example`` es el formato
       habitual en una plataforma de despliegue y antes impedía arrancar.
    2. El archivo ``.env`` del proyecto, que se inyecta en el entorno para
       que la fuente ``EnvSettingsSource`` lo resuelva como JSON (la fuente
       ``DotEnvSettingsSource`` usa el mismo decodificador).

    Sin este paso, cualquier proceso hijo que herede estas variables
    (Celery worker, scripts, jobs) abortaba con ``SettingsError``.
    """
    for clave in _CAMPOS_LISTA:
        if clave in os.environ:
            os.environ[clave] = _normalizar_lista(os.environ[clave])

    env_file = Settings.model_config.get("env_file")
    if isinstance(env_file, (list, tuple)):
        env_file = env_file[0] if env_file else None
    if not env_file:
        return
    for clave, valor in _leer_env_file(env_file).items():
        if clave in _CAMPOS_LISTA and clave not in os.environ:
            os.environ[clave] = _normalizar_lista(valor)


_preparar_listas_del_entorno()

# ``_exportar_a_environ`` (más abajo) vuelca también los valores por defecto
# de ``Settings`` al ``os.environ``, así que ``CORS_ORIGINS`` siempre acaba
# estando definido. Aquí, justo después de normalizar las listas, se anota si
# el valor venía realmente del entorno o del ``.env`` (o si es el default de
# la clase, ``["*"]``). Se usa para distinguir "comodín configurado a
# propósito" de "comodín por defecto".
_CORS_ORIGINS_EXPLICITO = "CORS_ORIGINS" in os.environ

settings = get_settings()


def _exportar_a_environ(obj: Settings) -> None:
    """Exporta los valores resueltos de ``Settings`` al ``os.environ``.

    Motivo
    ------
    ``pydantic-settings`` **lee** el archivo ``.env`` pero **no lo exporta**
    al ``os.environ``. Por eso todos los módulos legacy que consultan sus
    flags con ``os.getenv(...)`` veían ``None`` en desarrollo, mientras que
    en Railway (donde la plataforma sí inyecta las variables en el entorno)
    sí funcionaban. Esa asimetría producía bugs del tipo "en local el SMTP
    no se activa" o "el Dev Inbox ignora su configuración".

    Este exporte alinea ambos entornos **en un solo punto**, sin tocar los
    ~25 sitios que ya usan ``os.getenv``.

    Se hace en dos pasadas:

    1. Los campos declarados en ``Settings`` (ya tipados y normalizados:
       booleanos como ``"true"``, listas como ``"a,b"``).
    2. Las claves **restantes** del archivo ``.env`` (p. ej.
       ``DEV_INBOX_MAX``, ``ALLOW_XUSER_HEADER``, ``RESEND_API_KEY``), que no
       están declaradas en ``Settings`` pero sí se leen con ``os.getenv``.

    Reglas
    ------
    * Se usa ``setdefault``: si la variable ya existe en el entorno real
      (Railway, Docker, CI, shell), **esa gana**. Sólo se rellenan las que
      falten, de modo que nunca se pisa la configuración real del despliegue.
    * Las listas se exportan separadas por comas.
    * Los valores vacíos o ``None`` no se exportan (evita que un
      ``os.getenv("X", "defecto")`` reciba ``""`` en vez del defecto).
    """
    # Pasada 1: campos declarados en Settings (valores ya normalizados).
    for nombre, valor in obj.model_dump().items():
        if valor is None:
            continue
        if isinstance(valor, str) and not valor.strip():
            continue
        clave = nombre.upper()
        if clave in os.environ:
            continue
        if isinstance(valor, bool):
            os.environ[clave] = "true" if valor else "false"
        elif isinstance(valor, (list, tuple)):
            # Las listas se exportan como **JSON**, no como CSV: es el único
            # formato que ``pydantic-settings`` puede volver a leer desde el
            # entorno (ver ``_normalizar_lista``). Con CSV, cualquier proceso
            # hijo que herede estas variables (Celery worker, scripts, jobs)
            # abortaba al arrancar con ``SettingsError``.
            os.environ[clave] = json.dumps(list(valor), ensure_ascii=False)
        else:
            os.environ[clave] = str(valor)

    # Pasada 2: claves del .env que no están declaradas en Settings.
    env_file = Settings.model_config.get("env_file")
    if isinstance(env_file, (list, tuple)):
        env_file = env_file[0] if env_file else None
    if env_file:
        for clave, valor in _leer_env_file(env_file).items():
            if not valor.strip():
                continue
            os.environ.setdefault(clave, valor)


_exportar_a_environ(settings)
