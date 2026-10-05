# Inventario de datasets para detección de caídas

- Verificado el **2026-10-05** en las páginas oficiales de cada dataset (enlaces en cada
  ficha). Los datos que no se han podido confirmar en una fuente oficial se marcan como
  *(no verificado)*.
- Criterio del proyecto: quedarnos con los datasets **disponibles** y de **mayor calidad**,
  priorizando el volumen y la variedad (sujetos, escenas y, sobre todo, puntos de vista) para
  generalizar. Ver [CLAUDE.md](../../CLAUDE.md), "Fase actual: detector de caídas".
- Nuestro pipeline es **pose 2D sobre RGB → modelo temporal sobre esqueletos**. Por eso los
  datasets que solo tienen profundidad o térmico no sirven directamente (ver "Descartados").

## Resumen

1. **OmniFall** ([arXiv 2505.19889](https://arxiv.org/abs/2505.19889), v3 de julio de 2026)
   cambia el punto de partida. Unifica 8 datasets con escenas actuadas (*staged*) bajo una
   taxonomía común de 16 clases, con particiones por sujeto y por vista. Añade además 12 000
   vídeos sintéticos con edad y ángulo de cámara controlados, y un conjunto de test con
   caídas reales grabadas fuera de laboratorio. Su paquete `omnifall` (0.2.0, agosto de 2026)
   descarga 9 de los 10 componentes desde las fuentes originales, sin cuenta. Su taxonomía
   separa **`fall`** (la acción) de **`fallen`** (el estado posterior), que encaja con nuestros
   eventos `fall_suspected` / `fall_confirmed`.
2. **SAFER-Activities** (ECCV 2026) es el dataset con escenas actuadas más grande y realista
   disponible: 46 sujetos, más de 66 h, **5 406 caídas**, 8 cámaras tipo CCTV y actividades
   parecidas a una caída etiquetadas. Sus autores muestran que los modelos de **esqueleto**
   entrenados con él generalizan a otro dataset (F1 del 96,8 % en ImViA), mientras que los
   modelos solo RGB caen a F1 0 %. Es un argumento directo a favor de nuestro enfoque.
   Acceso con aprobación manual en Hugging Face.
3. **Personas mayores**: ningún dataset abierto tiene caídas reales de personas mayores. Lo
   más cercano:
   - **SFU / Databrary**: 300 vídeos de caídas reales en residencias, de personas de 58 a 98
     años. Requiere acuerdo institucional.
   - **KU Leuven HQFSD**: caídas reales de residentes reproducidas por actores en una
     habitación de residencia.
   - **OF-Synthetic**: caídas sintéticas con grupos de edad, incluidas personas mayores.
   - **Toyota Smarthome**: unas 187 h de actividad diaria real de 18 personas de 60 a 80 años,
     sin caídas. Es **la mejor fuente para medir falsos positivos por hora** con personas
     mayores.
4. Riesgo de licencias: casi todo es **solo uso no comercial / investigación**, y varios
   prohíben redistribuir o crear datasets derivados. Afecta a si se puede subir a Kaggle (ver
   "Licencias y Kaggle").

## Datasets RGB con caídas

Leyenda de **uso propuesto**: **E** = entrenamiento, **T** = solo test entre datasets,
**FP** = medición de falsos positivos por hora.

| Dataset | Año | Caídas / actividades normales (ADL) | Vistas y montaje | Sujetos | Licencia | Acceso | Uso |
|---|---|---|---|---|---|---|---|
| [SAFER-Activities](https://safer-activities.github.io/) | 2026 | 5 406 caídas; 85 310 instancias, 30 clases | 8 cámaras CCTV en laboratorio y 6 en una casa real; ángulos variados | 46 adultos, 18–58 años | CC BY-NC-SA 4.0 | HF con aprobación manual | E, T |
| [CMDFall](https://www.mica.edu.vn/perso/Tran-Thi-Thanh-Hai/CMDFALL.html) | 2018 | 8 tipos de caída (de pie, silla y cama) + 12 ADL | 7 Kinect: 6 a 1,8 m y 1 **cenital a 3 m** | 50, de 21 a 40 años | Investigación, gratis | Por correo | E |
| [UP-Fall](https://sites.google.com/up.edu.mx/har-up/) | 2019 | 5 tipos de caída + 6 ADL, 3 intentos cada uno (1 118 vídeos) | 2 vistas sincronizadas | 17, de 18 a 24 años | Cita obligatoria; permiso según OmniFall | Descarga web | E |
| [Le2i / ImViA](https://search-data.ubfc.fr/imvia/FR-13002091000019-2024-04-09_Fall-Detection-Dataset.html) | 2013 | 143 caídas / 48 ADL según el artículo original (otras fuentes dan cifras distintas) | 1 cámara; 4 escenarios (casa, cafetería, oficina, aula) | 9 | CC BY-NC-SA 3.0 | Descarga (vía `omnifall`) | E, T |
| [CAUCAFall](https://data.mendeley.com/datasets/7w7fccy7ky/4) | 2022 | 5 tipos de caída + 5 ADL por sujeto (100 vídeos) | 1 cámara; casa con oclusiones y luz natural, artificial y nocturna | 10, edades variadas (rango no verificado) | CC BY 4.0 | Mendeley, abierto | E |
| [GMDCSA-24](https://github.com/ekramalam/GMDCSA24-A-Dataset-for-Human-Fall-Detection-in-Videos) | 2024 | 79 caídas / 81 ADL | 1 webcam; 3 habitaciones | 4 | MIT | GitHub / Zenodo | E |
| [MCFD](https://www.iro.umontreal.ca/~labimage/Dataset/) (Montreal) | 2010 | 22 caídas + 24 eventos confusos (agacharse, sentarse, tumbarse en el sofá) | **8 cámaras IP** alrededor de la sala | **1** | Permiso de los autores | Descarga (vía `omnifall`) | T (invarianza de vista) |
| [UR Fall (URFD)](https://fenix.ur.edu.pl/~mkepski/ds/uf.html) | 2014 | 30 caídas / 40 ADL | 2 Kinect: frontal y **cenital**; las ADL solo en la frontal | no indicado en la web oficial | CC BY-NC-SA 4.0 | Descarga directa | T (vista cenital) |
| [KU Leuven HQFSD](https://iiw.kuleuven.be/onderzoek/advise/datasets) | 2016 | 55 escenarios de caída × 5 cámaras; 17 segmentos ADL (2 h 26 min de caídas y 5 h 50 min de ADL) | 5 webcams 640×480 a 12 fps en una **habitación de residencia** | 10 actores que **reproducen caídas reales de residentes** | Citar el artículo; sin licencia explícita | Box (enlace en la web) | T (realismo de residencia) |
| [OF-Synthetic (WanFall)](https://huggingface.co/datasets/simplexsigil2/wanfall) | 2025–26 | 12 000 vídeos (16,9 h), 16 clases, 30 mecanismos de caída | Ángulos generados con metadatos de elevación, azimut y distancia de cámara | Sintéticos: 6 grupos de edad (**incluye mayores**), etnia, IMC | CC BY-NC 4.0 | HF abierto (9 GiB) | E, T por edad |
| [OF-In-the-Wild (OOPS-Fall)](https://huggingface.co/datasets/simplexsigil2/omnifall) | 2020/2025 | 818 vídeos de **caídas reales** (2,65 h) | Sin control (vídeos de YouTube) | Muy variados | Anotaciones CC BY-NC-SA 4.0; licencia de los vídeos originales no explícita | Vía `omnifall` (44,6 GiB de descarga) | T |
| [FallVision](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/75QPKK) | 2025 | Caídas desde estar de pie, cama y silla, más vídeos sin caída (recuento no verificado) | **Cámara de mano** (móvil o cámara digital) | Voluntarios (no verificado) | CC0 | Dataverse abierto (49,6 GB) | E (secundario) |
| [MUVIM](https://arxiv.org/abs/2206.12740) | 2022 | ~300 caídas (adultos jóvenes) + 100 vídeos ADL de **mayores** | 6 sensores **en el techo**: IR, profundidad, térmico y RGB | 30 de 18–30 años + 10 de más de 70 | Restringida | Correo + formulario de privacidad | T, FP |

Notas por dataset:

- **SAFER-Activities.** Incluye "unstable", "lying down", "sitting down", "bending" y un
  subconjunto en silla de ruedas, todos útiles como negativos difíciles y para residencias.
  Las caídas las realizan actores adultos, no personas mayores. Incluye un subconjunto para
  evaluar estimación de pose (6 846 imágenes). Una fuente secundaria habla de 5 cámaras y 72
  escenarios; la página del artículo indica 8 cámaras en laboratorio y 6 en la casa.
- **CMDFall.** Es el mayor componente de OmniFall (7 h 25 min por vista). Sus ADL incluyen
  tambalearse, gatear y agacharse, que son negativos difíciles reales. La cámara cenital
  (Kinect7) aporta un punto de vista de residencia.
- **UP-Fall.** Se distribuye como fotogramas; `omnifall` reconstruye los vídeos, pero el
  proceso es lento. Sujetos muy jóvenes (18–24 años).
- **Le2i.** La web oficial (UBFC) está protegida contra robots y no se ha podido leer; la
  licencia está tomada de OmniFall. Las cifras varían entre fuentes (190–191 vídeos). Antes de
  usarlo hay que revisar sus anotaciones: algunos vídeos de caída no las tienen completas
  *(no verificado)*.
- **KU Leuven HQFSD.** Es lo más parecido a una residencia real: escenarios reproducidos a
  partir de caídas reales de residentes, con secuencias largas (2 min 45 s de media por
  escenario). El SAFER-Activities lo cita con 275 instancias de caída (55 × 5 vistas).
- **FallVision.** Al grabarse con cámara de mano, el punto de vista no se parece al de una
  cámara fija de residencia. Trae puntos del esqueleto en CSV, pero calculados con otro
  modelo; habría que volver a extraerlos con el nuestro.
- **MUVIM.** Ofrece la vista desde el techo y ADL de personas mayores, pero las caídas son
  solo de jóvenes.

## Datasets sin caídas (actividad normal) para falsos positivos

Fundamentales para la métrica de **falsos positivos por hora de actividad normal**, sobre
todo con personas mayores reales.

| Dataset | Contenido | Vistas | Sujetos | Licencia y acceso | Uso |
|---|---|---|---|---|---|
| [Toyota Smarthome](https://project.inria.fr/toyotasmarthome/) | Recortado: 16 115 clips de 31 actividades. Sin recortar: 536 vídeos de unos 21 min (**~187 h**) | 7 Kinect v1 en un piso | **18 mayores de 60 a 80 años** | Solo investigación académica; formulario (~3 días); RGPD; caras difuminadas | **FP** |
| [ETRI-Activity3D](https://ai4robot.github.io/etri-activity3d/) | 112 620 muestras de 55 acciones, entre ellas *lying down* | 8 vistas a 0,7 y 1,2 m (**altura de robot**, no de techo) | 50 mayores de 64 a 88 años + 50 jóvenes | Licencia firmada (EULA) que prohíbe ceder los datos a terceros; **vence el 31-12-2026 y obliga a borrarlos** | FP (corto plazo) |
| [NTU RGB+D 60/120](https://rose1.ntu.edu.sg/dataset/actionRecognition/) | "Falling down" (A43): unas 950 muestras (56 880 / 60 clases), más "staggering" (A42), sentarse, levantarse, recoger algo y agacharse | 3 Kinect v2 a −45°, 0° y +45° | 40 en NTU60; 106 en NTU120 | Solo académico; **prohíbe redistribuir y crear datasets derivados** | E (negativos), con cautela |

## Caídas reales de personas mayores

| Dataset | Contenido | Acceso | Uso |
|---|---|---|---|
| [SFU IPML / TIPS en Databrary](https://www.sfu.ca/ipml/research/data-sharing.html) | **300 vídeos de caídas reales** de 118 residentes de **58 a 98 años** (media 82,8) en zonas comunes de dos residencias (salas, comedores, pasillos), con ficha demográfica y clínica. Las cámaras son de vigilancia | Escribir a Steve Robinovitch (stever@sfu.ca). [Databrary](https://databrary.org/about/agreement/agreement-annex-III.html) exige que la **institución firme un acuerdo** y un investigador autorizado; un estudiante entra como afiliado de ese investigador | **T** (el test más honesto posible) |

Este es el único recurso que permite medir la limitación conocida del CLAUDE.md (las
personas mayores caen de otra forma) con datos reales. Se puede intentar a través de la UPCT,
con un profesor como investigador autorizado. Son vídeos sensibles y solo se usarían para
evaluación, siempre bajo el acuerdo correspondiente.

## Descartados y por qué

| Dataset | Motivo |
|---|---|
| EDF / OCCU ([Zenodo](https://zenodo.org/records/15494102)) | Solo **profundidad** (Kinect, sin RGB); nuestro modelo de pose trabaja sobre RGB. OmniFall los incluye en su versión de profundidad |
| SDUFall, TST Fall, conjuntos de cámara térmica | Solo profundidad o térmico |
| SisFall, UMAFall, FallAllD | Sensores en el cuerpo, sin vídeo |
| VFP290K | Personas caídas en exteriores (calle, parque), solo cajas delimitadoras y sin la secuencia de la caída. Poco parecido a una residencia. Podría servir para probar la pose de personas tumbadas vistas desde arriba |
| [Zenodo 17170592](https://zenodo.org/records/17170592) | Redistribución por un tercero de datasets cuyos autores **no permiten** redistribuirlos, publicada con licencia CC BY 4.0. Hay que usar las fuentes originales |
| Copias de Le2i y otros en Kaggle o Roboflow | Licencia y versión dudosas. Hay que usar las fuentes originales |

## Cobertura

**Punto de vista**, que es la invarianza que más nos importa:

- Desde el techo o en vertical: URFD (cámara 1), CMDFall (Kinect7, a 3 m) y MUVIM.
- Cámara alta tipo CCTV, varias a la vez: SAFER-Activities (8), MCFD (8) y KU Leuven (5).
- Ángulo de cámara controlado y anotado: OF-Synthetic. Permite estudiar el rendimiento en
  función de la elevación de la cámara, el factor clave en residencias.
- A la altura de los ojos: la mayoría de los datasets de una sola cámara.

**Edad:**

| Tipo de dato | Fuentes |
|---|---|
| Caídas reales de mayores | SFU (restringido) |
| Caídas reales de mayores, reproducidas por actores | KU Leuven |
| Caídas sintéticas de mayores | OF-Synthetic |
| Actividad diaria de mayores | Toyota Smarthome, ETRI-Activity3D, MUVIM |
| Caídas de actores jóvenes | Todo lo demás |

**Actividades difíciles** (negativos que el CLAUDE.md pide reportar por separado):

| Actividad | Fuentes |
|---|---|
| Tumbarse en la cama o en el sofá | SAFER (*lying down*), MCFD, CMDFall, ETRI (*lying down*), OmniFall (`lie_down`, `lying`) |
| Sentarse de golpe | UP-Fall, CAUCAFall, SAFER, NTU (A8), OmniFall (`sit_down`) |
| Agacharse y recoger algo del suelo | UP-Fall, CAUCAFall, CMDFall, MCFD, NTU (A6, A80), SAFER (*bending*) |
| Tambalearse o pérdida de equilibrio sin caída | CMDFall, NTU (A42), SAFER (*unstable*) |

## Licencias y Kaggle

- Lo que es **CC BY / CC0 / MIT** (CAUCAFall, GMDCSA-24, FallVision) o **CC BY-NC(-SA)**
  (SAFER, URFD, Le2i, OF-Synthetic) se puede usar en un proyecto de portafolio no comercial,
  citando a los autores.
- Para subir datos a Kaggle, aunque sea como dataset privado, hay que mirar cada licencia:
  - NTU prohíbe redistribuir y derivar nuevos datasets.
  - ETRI prohíbe ceder los datos a terceros.
  - CMDFall, MCFD y UP-Fall requieren permiso de los autores.
- **Propuesta:**
  1. Para los datasets con descarga abierta, el notebook de Kaggle los descarga **desde la
     fuente original** con `omnifall prepare` y no se resubir nada.
  2. Para los restringidos, la **extracción de poses se hace en local** (RTX 3050) y no se
     sube ni el vídeo ni los esqueletos derivados.
  3. El clasificador sobre esqueletos es ligero y puede entrenarse en local si hace falta.
- Esto también cumple el principio de privacidad del proyecto: los vídeos se procesan una vez,
  se quedan los esqueletos y nunca se versionan vídeos (ver `.gitignore`).

## Protocolo de evaluación propuesto (para discutir)

> **Actualización (2026-10-06):** se decidió entrenar **solo con SAFER-Activities**, y los
> demás datasets quedan para test entre datasets. Ver
> [docs/decisions/0007](../decisions/0007-fall-classifier-datasets.md). La propuesta de abajo
> se conserva como referencia por si hay que ampliar el entrenamiento.

1. **Entrenamiento:** SAFER-Activities + CMDFall + UP-Fall + CAUCAFall + GMDCSA-24 +
   OF-Synthetic (y NTU como negativos, si la licencia lo permite).
2. **Validación cruzada dejando un dataset fuera** con los datasets de OmniFall, usando sus
   particiones por sujeto y por vista para no mezclar sujetos entre entrenamiento y test.
3. **Test que nunca se usa para entrenar ni para ajustar umbrales:**

   | Dataset | Qué mide |
   |---|---|
   | Le2i | Comparabilidad con la literatura (SAFER da F1 96,8 % con esqueletos) |
   | URFD (vista cenital) | Robustez a la vista desde el techo |
   | MCFD | Invarianza con 8 vistas del mismo evento |
   | KU Leuven HQFSD | Realismo de residencia |
   | OF-In-the-Wild | Caídas reales |
   | SFU | Caídas reales de mayores, si se consigue acceso |

4. **Falsos positivos por hora** sobre las ~187 h de Toyota Smarthome sin recortar, con
   personas mayores reales. Además, tasa de falsos positivos en cada actividad difícil (tabla
   de "Cobertura").
5. **Latencia de detección:** requiere anotación del inicio de la caída a nivel de fotograma.
   La tienen OmniFall (segmentos con inicio y fin), SAFER, CMDFall y Le2i.

## Acciones pendientes (requieren al usuario)

> Tras la decisión [0007](../decisions/0007-fall-classifier-datasets.md), solo es necesaria
> la solicitud de **SAFER-Activities**. El resto queda como opción futura.

Solicitudes de acceso a nombre del usuario, por orden de prioridad:

1. **SAFER-Activities**: solicitud en Hugging Face (organización y uso previsto).
2. **CMDFall**: correo a thanh-hai.tran@mica.edu.vn.
3. **Toyota Smarthome**: formulario en la web del proyecto (correo institucional).
4. **SFU / Databrary**: hablar con la UPCT para tener un investigador autorizado y escribir a
   Steve Robinovitch.
5. *(Opcional)* **NTU RGB+D**, **MUVIM** (con formulario de privacidad) y **ETRI-Activity3D**
   (solo si da tiempo a usarlo antes del 31-12-2026).

Los datasets abiertos (Le2i, MCFD, UP-Fall, CAUCAFall, GMDCSA-24, URFD, OF-Synthetic y
OOPS-Fall) se pueden descargar ya con `omnifall` o desde su web, sin pedir nada.

## Fuentes principales

- OmniFall: [arXiv](https://arxiv.org/abs/2505.19889), [Hugging Face](https://huggingface.co/datasets/simplexsigil2/omnifall), [proyecto](https://dsch.ai/omnifall/), [paquete `omnifall`](https://pypi.org/project/omnifall/)
- SAFER-Activities: [arXiv 2609.08038](https://arxiv.org/abs/2609.08038), [proyecto](https://safer-activities.github.io/)
- Las fichas oficiales enlazadas en cada tabla.
