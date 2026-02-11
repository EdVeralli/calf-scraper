# CALF Scraper

Scraper automatizado para obtener informacion de cuentas de energia desde el Portal de Clientes de **CALF** (Cooperativa de Agua, Luz y Fuerza de Neuquen, Argentina).

## Funcionalidades

- Login automatico en el Portal de Clientes (sin password, solo tipo y numero de documento)
- Manejo de reCAPTCHA v2 con `undetected-chromedriver` (bypass automatico con perfil persistente)
- **Extraccion de cuentas**: numero, servicio, domicilio, estado de conexion
- **Detalle de cada cuenta**: asociado, domicilio completo, comprobantes pendientes (fecha emision, vencimiento, numero, importe, estado)
- **Deteccion de deuda**: cantidad de comprobantes adeudados e importe total
- **Exportacion CSV** automatica (nombre basado en tipo y numero de ID)
- Exportacion JSON para integracion con otros sistemas
- Guardado de screenshots y HTML de debug ante errores

## Requisitos

- Python 3.8+
- Google Chrome instalado

## Instalacion

```bash
# Clonar el repositorio
git clone https://github.com/EdVeralli/calf-scraper.git
cd calf-scraper

# Instalar dependencias
pip install -r requirements.txt
```

## Configuracion

### Paso 1: Crear el archivo .env

```bash
cp .env.example .env
```

### Paso 2: Configurar tus datos

Editar el archivo `.env`:

```env
# Tipo de identificacion: 1=DNI, 2=CUIT, 4=SOCIO
CALF_TIPO_ID=4
# Numero de identificacion
CALF_NRO_ID=123456
```

**IMPORTANTE:**
- El archivo `.env` contiene tus datos reales
- Este archivo esta en `.gitignore` y **nunca se sube al repositorio**

## Uso

### Reporte completo en consola + CSV
```bash
python calf_scraper.py
```

Esto genera:
- Reporte completo en consola (cuentas, detalle de deuda, comprobantes)
- Archivo CSV automatico: `calf_<tipo>_<numero>.csv` (ej: `calf_4_189163.csv`)

### Salida JSON
```bash
python calf_scraper.py --json
```

### Modo headless (sin navegador)
```bash
python calf_scraper.py --headless
```

**Nota:** En modo headless el reCAPTCHA puede no resolverse automaticamente. Se recomienda modo visible (por defecto) para la primera ejecucion.

## Manejo del reCAPTCHA

El portal CALF usa reCAPTCHA v2. El scraper lo maneja asi:

1. Abre Chrome con `undetected-chromedriver` (reduce deteccion de bots)
2. Usa un **perfil de Chrome persistente** (`chrome_profile/`) para mantener cookies entre ejecuciones
3. Llena tipo de ID y numero automaticamente (via JavaScript para compatibilidad con GeneXus)
4. Hace click automaticamente en el checkbox "No soy un robot"
5. Si el captcha se resuelve sin desafio de imagenes, continua automaticamente
6. Si aparece desafio de imagenes (primera ejecucion o muchos intentos), hay 120 segundos para resolverlo manualmente
7. Las cookies quedan guardadas en el perfil, por lo que las siguientes ejecuciones pasan sin captcha

## Salida de ejemplo

```
======================================================================
            REPORTE DE CUENTAS - CALF ENERGIA
======================================================================
Fecha del reporte: 10/02/2026 22:57
Nombre: PEREZ JUAN
Usuario: 10900123456000012
Persona: 123456
======================================================================

Cuentas encontradas: 2

 Cta  Servicio    Domicilio                                 Estado
---------------------------------------------------------------------------
   1  Energia     CALLE EJEMPLO 1234 NEUQUEN                CONECTADO
   2  Energia     OTRA CALLE 567 NEUQUEN                    CONECTADO

----------------------------------------------------------------------
  DETALLE CUENTA 1 - CALLE EJEMPLO 1234 NEUQUEN
----------------------------------------------------------------------
  Asociado: 123456/1: PEREZ JUAN
  Domicilio: CALLE EJEMPLO N°1234 S.C
  Detalle de deuda desde el 10/02/25

  [OK] SIN COMPROBANTES PENDIENTES

----------------------------------------------------------------------
  DETALLE CUENTA 2 - OTRA CALLE 567 NEUQUEN
----------------------------------------------------------------------
  Asociado: 123456/2: PEREZ JUAN
  Domicilio: OTRA CALLE N°567
  Detalle de deuda desde el 10/02/25

  [!] Comprobantes adeudados: 1
  [!] Importe adeudado: $52630.39

  Fecha Emis.  Fecha Vto.   Comprobante                    Importe Estado
  -------------------------------------------------------------------------
  20/01/26     06/02/26     FACT B-0021-20159538         52.630,39 Impaga

======================================================================
```

## Estructura del CSV

El CSV contiene las siguientes secciones:

| Seccion | Contenido |
|---------|-----------|
| DATOS DE LA PERSONA | Nombre, usuario, persona ID |
| CUENTAS | Tabla con todas las cuentas (nro, servicio, domicilio, estado) |
| DETALLE CUENTA N | Asociado, domicilio, estado de deuda, comprobantes adeudados, importe |
| COMPROBANTES | Fecha emision, fecha vencimiento, numero comprobante, importe, estado |

El archivo usa `;` como separador y encoding UTF-8 con BOM para compatibilidad con Excel.

## Estructura del Proyecto

```
calf-scraper/
├── .env.example       # Plantilla de configuracion (SI se sube al repo)
├── .env               # Datos reales (NO se sube al repo)
├── .gitignore         # Archivos ignorados por Git
├── README.md          # Este archivo
├── requirements.txt   # Dependencias Python
├── calf_scraper.py    # Script principal
└── chrome_profile/    # Perfil Chrome persistente (NO se sube al repo)
```

## Solucion de problemas

### Error: "Falta CALF_NRO_ID"
Verificar que existe el archivo `.env` con la variable `CALF_NRO_ID` configurada.

### El captcha muestra desafio de imagenes
Esto ocurre normalmente en la primera ejecucion o despues de muchos intentos. Resolver manualmente una vez; las cookies se guardan en `chrome_profile/` para las siguientes ejecuciones.

### Error de Chrome/ChromeDriver
Asegurarse de tener Google Chrome instalado. `undetected-chromedriver` descarga automaticamente el ChromeDriver compatible.

### Error "session not created: This version of ChromeDriver only supports Chrome version X"
Si la version de Chrome no coincide con el ChromeDriver, ajustar el parametro `version_main` en la funcion `crear_driver()` del script.

## Licencia

MIT
