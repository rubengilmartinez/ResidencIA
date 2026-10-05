# Datos de entrenamiento y evaluación

Aquí solo hay scripts e instrucciones; los datos **nunca** se versionan. El inventario y la
justificación de cada dataset están en
[docs/datasets/fall_datasets.md](../../docs/datasets/fall_datasets.md).

## Dónde viven los datos

`C:\data\residencia\` (o la ruta de la variable `RESIDENCIA_DATA_DIR`): fuera del repositorio,
de OneDrive y de Google Drive. Así no se suben a la nube, como exigen las licencias y la
privacidad. Estructura:

```
C:\data\residencia\
└── omnifall\                 # vídeos de los componentes de OmniFall
    ├── up_fall\video\...     # {root}/{dataset}/video/{path}.mp4
    ├── downloads\            # temporal: omnifall borra cada archivo tras convertirlo
    └── logs\
```

Los vídeos solo se necesitan para extraer las poses. Se conservan hasta fijar el modelo de
pose y validar los esqueletos; después se pueden borrar y quedarse solo con los esqueletos,
que ocupan menos de 1 GB en total.

## Datasets de entrenamiento del clasificador

| Dataset | Acceso | Qué descargar | Tamaño |
|---|---|---|---|
| SAFER-Activities | [Hugging Face](https://huggingface.co/datasets/SAFER-Activities/SAFER-Activities), aprobación manual | `raw/Safer-Activities-Full-Dataset/normal/` y `raw/SAFER-Activites-Test-Dataset/` (no `extracted_features/`) | ~96 GB de 172,9 GB |
| CMDFall | Correo a thanh-hai.tran@mica.edu.vn | Solo RGB (`colors/`) | Sin publicar; estimado 90–180 GB |
| UP-Fall | Abierto (Google Drive) | `omnifall prepare up_fall` | ~110 GB de transferencia; unos pocos GB en disco |

Duraciones, calculadas con las anotaciones de OmniFall: CMDFall 51,1 h (7 vistas), UP-Fall
9,3 h (2 vistas).

## UP-Fall

```powershell
Start-Process powershell -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','ml\datasets\download_up_fall.ps1' -WindowStyle Hidden
Get-Content C:\data\residencia\omnifall\up_fall_status.txt
```

- `omnifall` 0.2.0 lee los 1 118 enlaces de la web del dataset y descarga, convierte a MP4
  y borra cada zip de uno en uno. Si se interrumpe, continúa donde se quedó.
- **Cuota de Google Drive:** los ficheros de UP-Fall se descargan mucho y Google Drive
  responde a menudo "Quota exceeded" (puede tardar hasta 24 h en liberarse). El script
  reintenta cada 3 h, como máximo 8 veces. No se fuerza la descarga por partes para esquivar
  el límite.
- `omnifall` 0.2.0 necesita `requests` aunque no lo declare, y `ffmpeg` en el `PATH`.
