# CALF Scraper

Scraper automatizado para obtener informacion de cuentas de energia desde el Portal de Clientes de **CALF** (Cooperativa de Agua, Luz y Fuerza de Neuquen, Argentina).

## Funcionalidades

- Login automatico en el Portal de Clientes (sin password, solo tipo y numero de documento)
- Manejo de reCAPTCHA v2 con `undetected-chromedriver` (bypass automatico o resolucion manual)
- **Extraccion de cuentas**: numero, servicio, domicilio, estado de conexion
- **Detalle de cada cuenta**: suministro, medidor, tarifa, lecturas, importes, tablas de datos
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
- Reporte en consola con todas las cuentas y sus detalles
- Archivo CSV automatico: `calf_<tipo>_<numero>.csv` (ej: `calf_4_189163.csv`)

### Salida JSON
```bash
python calf_scraper.py --json
```

### Modo headless (sin navegador)
```bash
python calf_scraper.py --headless
```

**Nota:** En modo headless el reCAPTCHA puede no resolverse automaticamente. Se recomienda modo visible (por defecto) para poder resolver el captcha manualmente si es necesario.

## Manejo del reCAPTCHA

El portal CALF usa reCAPTCHA v2. El scraper lo maneja asi:

1. Abre Chrome con `undetected-chromedriver` (reduce deteccion de bots)
2. Llena tipo de ID y numero automaticamente
3. Si el captcha no se resuelve solo en 5 segundos, muestra: **"Resuelve el captcha en el navegador"**
4. Tenes 120 segundos para hacer click en "No soy un robot" en la ventana de Chrome
5. Una vez resuelto, el script continua automaticamente

## Salida de ejemplo

```
======================================================================
            REPORTE DE CUENTAS - CALF ENERGIA
======================================================================
Fecha del reporte: 10/02/2026 15:30
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
  suministro: 12345678
  medidor: 98765
  tarifa: T1R
  ...

======================================================================
```

## Estructura del CSV

El CSV contiene las siguientes secciones:

| Seccion | Contenido |
|---------|-----------|
| DATOS DE LA PERSONA | Nombre, usuario, persona ID |
| CUENTAS | Tabla con todas las cuentas (nro, servicio, domicilio, estado) |
| DETALLE CUENTA N | Detalle de cada cuenta (suministro, medidor, tarifa, importes, tablas) |

El archivo usa `;` como separador y encoding UTF-8 con BOM para compatibilidad con Excel.

## Estructura del Proyecto

```
calf-scraper/
├── .env.example       # Plantilla de configuracion (SI se sube al repo)
├── .env               # Datos reales (NO se sube al repo)
├── .gitignore         # Archivos ignorados por Git
├── README.md          # Este archivo
├── requirements.txt   # Dependencias Python
└── calf_scraper.py    # Script principal
```

## Solucion de problemas

### Error: "Falta CALF_NRO_ID"
Verificar que existe el archivo `.env` con la variable `CALF_NRO_ID` configurada.

### El captcha no se resuelve automaticamente
Ejecutar sin `--headless` para poder resolver el captcha manualmente en la ventana de Chrome.

### Error de Chrome/ChromeDriver
Asegurarse de tener Google Chrome instalado. `undetected-chromedriver` descarga automaticamente el ChromeDriver compatible.

### Datos de detalle vacios
La primera vez que se ejecuta, el extractor de detalle es generico. Si una pagina de detalle no se parsea bien, se guardan screenshots y HTML en la carpeta `debug/` para poder ajustar los selectores.

## Licencia

MIT
