# Datos de entrenamiento y evaluación

Aquí solo hay scripts e instrucciones; los datos **nunca** se versionan. La elección de
datasets está en [docs/decisions/0007](../../docs/decisions/0007-fall-classifier-datasets.md)
y el inventario completo en
[docs/datasets/fall_datasets.md](../../docs/datasets/fall_datasets.md).

## Dónde viven los datos

`C:\data\residencia\` (o la ruta de la variable `RESIDENCIA_DATA_DIR`): fuera del repositorio,
de OneDrive y de Google Drive (la unidad G: es Google Drive y sincroniza con la nube). Así no
se suben a la nube, como exigen las licencias y la privacidad.

Los vídeos solo se necesitan para extraer las poses. Se conservan hasta fijar el modelo de
pose y validar los esqueletos; después se pueden borrar y quedarse solo con los esqueletos.

## SAFER-Activities (entrenamiento)

1. **Acceso:** solicitarlo en <https://huggingface.co/datasets/SAFER-Activities/SAFER-Activities>.
   La aprobación es manual.
2. **Token:** crear uno de lectura en <https://huggingface.co/settings/tokens> e iniciar
   sesión, una sola vez:

   ```powershell
   uvx --from huggingface_hub hf auth login
   ```

3. **Descarga** de lo necesario, unos 96 GB de los 172,9 GB del repositorio:

   ```powershell
   uvx --from huggingface_hub hf download SAFER-Activities/SAFER-Activities --repo-type dataset `
     --include "raw/Safer-Activities-Full-Dataset/normal/*" `
     --include "raw/SAFER-Activites-Test-Dataset/*" `
     --include "splits/*" --include "README.md" `
     --local-dir C:\data\residencia\safer
   ```

| Carpeta | Contenido | Tamaño |
|---|---|---|
| `raw/Safer-Activities-Full-Dataset/normal/` | 467 vídeos (8 cámaras CCTV, laboratorio) y 60 CSV de etiquetas | 87,6 GB |
| `raw/SAFER-Activites-Test-Dataset/` | 30 vídeos de una casa real (fuera del laboratorio) y sus CSV | 8,6 GB |
| `splits/` | Particiones oficiales por sujeto y por vista | < 1 MB |

No se descargan:

- `extracted_features/` (55,5 GB): características para modelos RGB.
- `raw/.../wheelchair/` (14,9 GB): subconjunto de silla de ruedas, que se puede añadir más
  adelante.
- `pose_bboxes/` y `wheelchair_keypoints/`: puntos del esqueleto calculados con otro modelo.
  Para entrenar usaremos los nuestros, porque el clasificador debe ver esqueletos del mismo
  modelo de pose que se usará en producción.

`hf download` reanuda si se interrumpe. Los nombres de carpeta, incluida la errata
"Activites", son los del repositorio original.
