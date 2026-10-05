# 0007. Datasets del clasificador de caídas: entrenar solo con SAFER-Activities

- Estado: aceptada
- Fecha: 2026-10-06

## Contexto

El detector de caídas usa un modelo de pose preentrenado (elegido en la comparativa B2) y un
clasificador temporal sobre esqueletos, que es lo que hay que entrenar. El
[inventario de datasets](../datasets/fall_datasets.md) propuso entrenar con SAFER-Activities,
CMDFall y UP-Fall.

Al intentarlo:

- UP-Fall son unos 110 GB de transferencia desde Google Drive, que bloquea las descargas por
  exceso de cuota ("Quota exceeded") durante horas.
- CMDFall requiere solicitar acceso por correo y pesa unos 90–180 GB estimados.

## Alternativas

1. SAFER-Activities + CMDFall + UP-Fall: más variedad de sujetos y escenas, más esfuerzo de
   obtención.
2. **Solo SAFER-Activities:** un único dataset grande y moderno, con una única vía de acceso.

## Decisión

Opción 2, elegida por el usuario por simplicidad. SAFER-Activities incluye:

- 46 sujetos de 18 a 58 años y **5 406 caídas**.
- 8 cámaras tipo CCTV en laboratorio y un conjunto de test en una casa real.
- Actividades parecidas a una caída etiquetadas, particiones oficiales por sujeto y por vista,
  y licencia CC BY-NC-SA 4.0.

Se descargan unos 96 GB (ver [ml/datasets/README.md](../../ml/datasets/README.md)).

Evaluación, según exige el CLAUDE.md:

- **Dentro de SAFER:** partición por **sujeto** (validación) y por **vista** (generalización
  a cámaras no vistas), más su test fuera del laboratorio.
- **Entre datasets, solo test** (nunca se entrena ni se ajustan umbrales con ellos): Le2i,
  CAUCAFall, GMDCSA-24, URFD (vista cenital), MCFD (8 vistas), KU Leuven HQFSD (habitación de
  residencia) y OOPS-Fall (caídas reales). Todos son de descarga abierta.
- **Falsos positivos por hora:** Toyota Smarthome (personas mayores), cuando haya acceso.

## Consecuencias

- Una sola fuente de entrenamiento significa los mismos escenarios y la misma instalación de
  cámaras, con riesgo de sobreajuste a ese entorno. La evaluación entre datasets lo medirá.
  Como referencia, los autores de SAFER obtienen F1 96,8 % en ImViA con esqueletos.
- **Si la generalización entre datasets es pobre, el primer paso será añadir CMDFall o
  UP-Fall**, que siguen documentados en el inventario.
- Solo adultos de 18 a 58 años: sigue vigente la limitación conocida sobre personas mayores.
- Pendiente al ver las anotaciones: cómo se etiqueta en SAFER el estado de "caído en el suelo"
  (las clases publicadas incluyen *fall*, *lying posture* y *lying down*), porque nuestro
  diseño separa la caída de la inmovilidad posterior (ver 0003 y 0006).
- Todo queda a la espera de que los autores aprueben el acceso en Hugging Face.
