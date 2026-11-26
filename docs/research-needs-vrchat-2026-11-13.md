# Necesidades reales de creadores de mundos VRChat al gestionar assets 3D
## Investigación para VRChat Asset Vault (Windows, gratis, local-first, open source)

**Fecha de investigación:** 13 de noviembre de 2026
**Método:** búsqueda web + lectura directa de la documentación oficial de VRChat (`creators.vrchat.com`). No se crearon cuentas, no se publicó nada, no se gastó dinero.
**Limitación honesta:** los foros r/VRChat y VRChat Ask Forum devolvieron pocos hilos directos en buscador y los Discord de creadores son cerrados/inaccesibles desde fuera, por lo que el dolor "de foro" se triangula desde la documentación oficial, guías de la comunidad (VRCreators, VRCLibrary, Ask Forum) y las herramientas que existen para taparlo. No hay cifras de encuesta propias: no se inventa ningún porcentaje ni número de usuarios.

---

## 1. Top 8 necesidades reales, priorizadas

### N1. Saber ANTES de importar si un asset rompe el presupuesto Quest — el dolor nº 1
Hoy el creador solo descubre el problema al final: tras importar a Unity, configurar y pulsar Build & Publish en el SDK. La documentación oficial dice explícitamente que el tamaño solo se ve *después* de construir ("You can see the size of your assets once you've built the content… and search your Editor log for 'statistics'") y que el SDK bloquea la subida si se excede el límite. Es decir: el feedback llega tarde, cuando el asset ya está dentro del proyecto y la escena construida a su alrededor.
- Fuente: https://creators.vrchat.com/platforms/android/quest-content-optimization/
- Implicación para el Vault: la ficha por asset (tris, materiales, texturas, tamaño, semáforo PC/Quest) **antes** de abrir Unity es exactamente el hueco. Ninguna herramienta de las investigadas lo hace fuera de Unity.

### N2. El mundo se pasa de 100 MB en Quest y no se sabe qué lo infla
El límite duro es 100 MB tras compresión en Android/Quest. Los culpables habituales, según la guía oficial y las guías de optimización, son texturas (>1K), lightmaps, audio y assets no usados que se cuelan en el build. La trampa documentada: la compresión Crunch reduce el tamaño de descarga pero **no** reduce el coste en memoria — "Your content package should be within the limits without Crunch".
- Fuentes:
  - https://creators.vrchat.com/platforms/android/quest-content-optimization/
  - https://www.vrcreators.net/docs/vrchat/android-mobile-worlds-guide
  - https://vrclibrary.com/wiki/books/create-your-first-vrchat-world/page/uploading-to-vrchat-and-quest-compatibility ("Quest worlds have a size limit of 100MB. If it goes over the world will not upload. The quickest ways to fix this are to compress/lower the resolution of textures/lightmaps/meshes/audio files…")
- Implicación: el Vault debe mostrar tamaño de archivo **y** memoria estimada de texturas por asset, y sumar el presupuesto del mundo/colección, no solo fichas aisladas. Un asset "pequeño en disco" puede ser enorme en VRAM (una textura 4096 sin comprimir ≈ 64 MB, según VR Cooperative).

### N3. Encontrar assets entre carpetas: Downloads, Booth, Gumroad, .unitypackage, FBX sueltos
El flujo real es caótico: se compran/descargan assets de Booth.pm, Gumroad, Unity Asset Store y sitios gratuitos; quedan en Downloads, en carpetas por tienda, dentro de `.unitypackage` o como FBX/OBJ sueltos. Las guías de iniciación lo reconocen de frente: recomiendan crear la estructura `Assets/Scenes, Materials, Textures, Models, Prefabs, Audio, Scripts` *antes* de importar nada, "saves future-you from digging through a messy `Assets` folder at 2 AM", y advierten "only download free assets you think you'll actually use". La prueba de que el dolor es real y no resuelto: existe un plugin entero, **Assets Manager for VRChat**, cuya promesa es literalmente "so you never dig through `Assets/` folder-by-folder again" (grupos, portadas, apodos, enlaces a tienda, notas, tags, búsqueda instantánea).
- Fuentes:
  - https://www.vrcreators.net/docs/vrchat/setting-up-vrchat-creator-companion
  - https://vrclibrary.com/wiki/books/the-vrchat-creation-compendium/page/basic-upload-and-modelling-worlds
  - https://vpm-catalog.vercel.app/packages/com.alanbacker.assets-manager-for-vrchat/
- Implicación: búsqueda + tags + colecciones por mundo + vista previa sin abrir Blender/Unity es necesidad central, no adorno. Es lo que LocalFab vende como titular ("preview assets without opening Blender") y lo que Meshory vende para impresión 3D ("Rediscover the models you already own").

### N4. La importación manual es repetitiva y frágil: escala, rotación, materiales rosas
Cada asset importado a mano exige los mismos pasos: arrastrar FBX/OBJ a `Assets/`, corregir Scale Factor (el clásico modelo 100× demasiado grande o microscópico por centímetros vs. metros; el famoso `0.01`/`100` de Blender→FBX), rotación -90° en X, extraer texturas/materiales, reasignar shaders porque el material sale rosa (shader no encontrado/incompatible), y para avatares además Rig → Humanoid y descriptor. VRChat recomienda oficialmente **no usar `.blend` directamente**: "Avoid directly using `.blend` files. Exporting FBX files from Blender for use in VRChat usually causes fewer issues."
- Fuentes:
  - https://creators.vrchat.com/worlds/submitting-a-world-to-be-made-public
  - https://uhiyama-lab.com/en/notes/vrchat/world-import-assets/ ("It's pink → shader isn't working… Giant or microscopic → Fix Scale Factor… On its side, or 90 degrees off → Rotation X -90")
  - https://app.cinevva.com/guides/blender-to-unity-export-checklist (FBX Units Scale vs. All Local y el origen del 0.01)
  - https://www.vrcreators.net/docs/unity3d/how-to-apply-a-texture-to-an-object
- Implicación: el Vault debería detectar y avisar de escala/unidades, materiales sin textura y shaders problemáticos **en la ficha**, y el export a Unity debería llevar la carpeta limpia (modelo + texturas + manifiesto) para que el import sea arrastrar-y-listar, no cazar archivos.

### N5. Mantener dos versiones, PC y Quest, a mano
El mundo PC y el Android deben compartir el mismo blueprint ID para ser un solo mundo multiplataforma, y los objetos sincronizados deben estar en el mismo lugar de la jerarquía y con los mismos nombres en ambas versiones. Cambiar de plataforma exige cambiar shaders a variantes móviles, quitar post-procesado (desactivado por completo en Android), quitar/ajustar transparencias y GrabPass, bajar texturas y audio. Las guías advierten que el primer cambio a Quest es lento y que es mejor corregir primero la versión PC. EasyQuestSwitch existe precisamente para automatizar estos cambios al cambiar de plataforma.
- Fuentes:
  - https://www.vrcreators.net/docs/vrchat/quest-compatibility-checklist
  - https://vrclibrary.com/wiki/books/create-your-first-vrchat-world/page/uploading-to-vrchat-and-quest-compatibility
  - https://vcc.docs.vrchat.com/vpm/curated-community-packages/ (EasyQuestSwitch)
- Implicación: el semáforo **doble** PC/Quest por asset (no un solo semáforo) es un acierto de diseño; idealmente la ficha indicaría también qué shader usa y si es apto para móvil.

### N6. Licencias: cada vendedor de Booth/Gumroad tiene sus propias reglas, y el origen se pierde
No hay una licencia única. Los términos por vendedor prohíben casi siempre redistribuir/revender/recompartir los archivos originales, exigen que cada parte tenga su propia copia legítima para comisiones, distinguen licencia personal vs. comercial (uso en modelos públicos, venta como parte de un avatar completo con precio mínimo, crédito obligatorio con enlace a la tienda), y algunos prohíben uso en mundos públicos o exigen licencia aparte para distribuir en un juego/app. Si el creador pierde el enlace de origen y la licencia, no puede demostrar qué puede hacer con ese asset — y un export que redistribuya archivos comprados violaría esos términos.
- Fuentes (ejemplos de términos reales por vendedor):
  - https://www.cookistudio.com/rss-docs/docs/license/ ("You may not: Share, redistribute, transfer, or resell the purchased files…")
  - https://tos.starkim1999.com/products/tsukuyomi/ ("Do not resell or share the raw asset files… You may not use the product on public VRChat models under the Personal License")
  - https://www.kissu.shop/ ("Redistribution, resale, reuploading, or file sharing is strictly prohibited… For commissions… both the creator and the customer must own a legitimate copy")
- Implicación: el manifiesto de origen/licencia en el export no es un extra: es la función que hace legal y reutilizable la librería. Guardar autor, URL, licencia y fecha de compra por asset es una necesidad real y diferenciadora. **El Vault debe exportar solo los assets propios del usuario y nunca redistribuir modelos de terceros** (coherente con el diseño MIT/vacío ya decidido).

### N7. Draw calls y materiales: el presupuesto que no se ve en el contador de triángulos
Cada material adicional crea un submesh y cuesta draw calls; VRChat insiste en minimizar el número de materiales del mundo y en pensar el mundo como colección de objetos con materiales combinados por atlas (p. ej. silla/sombrilla/manta = un material y un atlas; rocas = otro), pero advierte contra fusionar con demasiada agresividad porque se pierde occlusion culling y batching. Un mundo de 200k tris con 900 draw calls rinde peor que uno de 1M de tris con 30 draw calls (según la skill comunitaria de optimización; es criterio secundario, no cifra oficial — ver §3).
- Fuentes:
  - https://creators.vrchat.com/platforms/android/quest-content-optimization/ ("Additional materials creates additional submeshes, which costs draw calls… You should aim to have the minimal possible material count for your world")
  - https://www.vrcreators.net/docs/vrchat/world-optimization-checklist
- Implicación: la ficha debe contar **materiales y submeshes por asset**, no solo tris; y la vista de colección/mundo debe sumar materiales y estimar draw calls. Es un dato que hoy solo se obtiene dentro de Unity con el Profiler.

### N8. El rendimiento es de la escena completa, no del asset: luces, espejos, vídeo, lightmaps
La guía oficial de publicación pide: al menos 45 FPS con un solo usuario VR en el spawn; hornear iluminación (las luces en tiempo real son "muy caras", "no es irrazonable descartarlas por completo"); lightmaps de baja resolución + light probes; hornear occlusion culling ("exceedingly important"); **máximo 1 espejo por sala y con toggle, nunca activado por defecto; máximo 2 video players por sala**. Un asset puede pasar su ficha individual y aun así el mundo fallar por la suma.
- Fuente: https://creators.vrchat.com/worlds/submitting-a-world-to-be-made-public (verificado por lectura directa, 13 nov 2026)
- Implicación: el Vault no puede prometer "mundo optimizado" desde fichas aisladas; lo honesto y útil es el presupuesto agregado por colección/mundo (tris + materiales + texturas + tamaño) con alertas, y dejar la validación final al SDK/VRWorld Toolkit dentro de Unity. No sobredimensionar la promesa.

---

## 2. Flujo típico carpeta → Unity/VCC (pasos manuales y repetitivos)

1. **VCC:** instalar/actualizar Unity 2022.3.22f1 y el SDK de mundos (o avatares) mediante el Creator Companion; crear proyecto desde la plantilla World; no descargar Unity a mano (error nº 1: versiones incompatibles).
2. **Localizar el asset** en Downloads / carpeta de Booth / .unitypackage / FBX suelto (aquí se pierde tiempo: N3).
3. **Importar:** arrastrar FBX/OBJ (o .unitypackage) a `Assets/`; para `.blend`, exportar primero a FBX en Blender (recomendación oficial).
4. **Reparar import:** Scale Factor (0.01/100×), rotación, extraer texturas/materiales, reasignar shader si sale rosa, revisar UVs.
5. **Colocar en escena:** arrastrar a la jerarquía, marcar Static si es prop estático, añadir colliders, ajustar escala/posición a mano.
6. **Materiales/texturas por asset:** bajar Max Size, compresión, Crunch, atlas; quitar texturas no usadas.
7. **Luces y rendimiento:** hornear lightmaps + light probes + occlusion culling; revisar espejos/video players/luces realtime.
8. **Versión Quest:** cambiar a Android, aplicar overrides de textura/shader (o EasyQuestSwitch), mantener mismo blueprint ID y jerarquía/nombres sincronizados.
9. **Validar:** SDK Build panel / VRWorld Toolkit World Debugger (90+ checks) / Build Report; corregir; Build & Test; Build & Publish.
10. **Repetir** 3–9 por cada asset y en cada iteración. Nada de esto existe como vista previa antes del paso 3: ese es el hueco.

Fuentes del flujo:
- https://generalistprogrammer.com/tutorials/how-to-make-a-vrchat-world
- https://proofly.store/3d-models-for-vrchat (pipeline FBX → Unity → VRChat SDK)
- https://www.vrcreators.net/docs/vrchat/setting-up-vrchat-creator-companion
- https://creators.vrchat.com/platforms/android/quest-content-optimization/

---

## 3. Límites VRChat verificados (con fuente y grado de certeza)

### Mundos — Android / Quest (fuente primaria oficial, leída directamente)
| Métrica | Valor | Tipo | Fuente |
|---|---|---|---|
| Tamaño mundo comprimido (Android) | **≤ 100 MB tras compresión** (104.857.600 bytes) | **Límite duro**: no se puede subir ni acceder | https://creators.vrchat.com/platforms/android/quest-content-optimization/ |
| Triángulos totales del mundo (Android) | **≈ 250.000 tris en total** (recomendado, dejar sitio para avatares) | Recomendación, no límite duro | misma página oficial |
| Texturas (Android) | **máx. 1024×1024**; evitar >1K | Recomendación | misma página oficial |
| Materiales (mundo) | **mínimo posible**; sin cifra | Recomendación cualitativa | misma página oficial |
| Shaders (mundo Android) | Custom permitidos, con extremo cuidado; recomendado `Mobile/VRChat/Lightmapped` + luz horneada; **evitar transparencia** (alpha fill rate) | Recomendación | misma página oficial |
| Iluminación (mundo) | **Hornear es esencial**; luces realtime muy caras; lightmaps baja resolución + light probes | Recomendación | misma página oficial |
| Occlusion culling | **Hornear es "exceedingly important"** | Recomendación | misma página oficial |
| Post-procesado (Android) | **Desactivado por completo** (v1 y v2) | Límite duro de plataforma | https://creators.vrchat.com/platforms/android/quest-content-limitations/ |
| Cloth (Android) | **Desactivado por completo** | Límite duro | misma página |
| Audio sources (mundo Android) | Permitidas pero **restringidas**; en avatares desactivadas por completo | Restricción | misma página |
| Cámaras (mundo Android) | Permitidas, sin excederse; en avatares desactivadas | Restricción | misma página |

### Mundos — PC (fuente primaria oficial, leída directamente)
| Métrica | Valor | Tipo | Fuente |
|---|---|---|---|
| Tamaño mundo PC | **Sin límite duro del SDK**; VRChat pide mantener mundos públicos **por debajo de 200 MB** ("Try to keep your worlds under 200MB") | Petición, no límite duro | https://creators.vrchat.com/worlds/submitting-a-world-to-be-made-public |
| Rendimiento en spawn | **≥ 45 FPS con un solo usuario VR en el spawn** | Objetivo de publicación / Community Labs | misma página |
| Espejos | **Máx. 1 por sala, con toggle, no activado por defecto** | Recomendación fuerte | misma página |
| Video players | **Máx. 2 por sala** | Recomendación fuerte | misma página |
| `.blend` directo | Evitar; exportar FBX | Recomendación oficial | misma página |
| Unity | **2022.3.22f1**, Built-in Render Pipeline | Versión soportada | https://www.vrcreators.net/docs/vrchat/setting-up-vrchat-creator-companion ; skill comunitaria verificada 2026-10-17 (Unity 6: uploads rechazados — secundario) |

### Avatares — para contexto (NO confundir con límites de mundo)
Los límites de tamaño de avatar **no** son límites de mundo. Se incluyen porque muchos assets de mundo se juzgan con lógica de avatar por error:
| Métrica | PC | Android/Quest | Fuente |
|---|---|---|---|
| Tamaño descarga / sin comprimir (avatar) | 200 MB / 500 MB | 10 MB / 40 MB | https://creators.vrchat.com/avatars/avatar-size-limits/ |
| Tris Excellent / Good (avatar) | 32.000 / 70.000 | 7.500 / 10.000 | Sistema de Performance Ranking, vía https://github.com/vrcd-community/vrchat-docs-localization/blob/HEAD/docs/creators.vrchat.com/avatars/avatar-performance-ranking-system.md y https://proofly.store/3d-models-for-vrchat |
| Tris Medium / Poor (avatar) | 70.000* / 70.000* | 15.000 / 20.000 | idem (*en PC el ranking de tris se satura en 70k: por encima es Very Poor directamente) |
| Memoria de texturas Excellent / Good (avatar) | 40 MB / 75 MB | 10 MB / — | idem PC verificado; Quest Good no verificado en fuente primaria — **no usar cifra sin verificar** |
| Materiales Excellent (avatar) | ≤ 4 (PC) | 1 (Quest) | idem, secundario |

### Cifras que NO se pudieron verificar — no usar como hechos
- **Límite duro de tris por mesh individual en mundos:** no existe en la documentación oficial encontrada; solo la recomendación agregada de 250k por mundo (Quest). No inventar un "máx. por mesh".
- **Límite duro de materiales/texturas por mundo:** no existe cifra oficial; solo "mínimo posible".
- **Tamaño sin comprimir de mundo:** no hay cifra oficial encontrada equivalente al 500 MB de avatar. No usarla.
- **SetPass calls <150 PC / <50 móvil; mundo PC 500k–1M tris "viable"; textura PC máx. 2048 (4096 solo hero):** aparecen solo en la skill comunitaria https://github.com/matty/agent-skills/blob/HEAD/skills/vrchat-world-optimization/SKILL.md (revisada 2026-10-17). Son criterios razonables de segunda mano, **no** cifras oficiales: úsense como umbrales internos configurables, etiquetados como tales.
- **"50.000 tris recomendados para mundos Quest"** en una guía de Steam (https://steamcommunity.com/sharedfiles/filedetails/?id=2507157026): contradice la cifra oficial de 250.000; es un texto antiguo/desactualizado. **Prevalece la oficial: 250.000.**
- **Límites de audio/lightmaps en MB o resolución:** no hay cifras duras oficiales encontradas; solo recomendaciones cualitativas.

---

## 4. Qué cubre y qué NO cubre cada competidor

| Herramienta | Qué cubre | Qué NO cubre (hueco para el Vault) | Precio / plataforma |
|---|---|---|---|
| **BlenderKit / Blendkit** (renombrado jun 2026) | Base de datos online de modelos/materiales/HDRIs dentro de Blender; ~23.700 modelos gratis (oct 2026), resto con plan Full de pago; cuenta obligatoria; licencias por asset (Royalty Free/CC0) | Es una **tienda/biblioteca online para Blender**, no una librería de archivos propios; no gestiona FBX/OBJ/GLB sueltos en disco; no mide presupuestos VRChat; no exporta a Unity; solo Blender | Gratis parcial + suscripción Full; Blender only. Fuentes: https://supavoxel.com/guides/free-3d-models-for-blender , https://the3dai.com/ai-3d-texturing/blog/free-blender-assets |
| **Blender Asset Browser** (nativo) | Catálogos, tags y previews de assets **.blend** marcados como asset | Solo .blend; hay que marcar cada asset a mano; Blender **no copia** el asset a la librería (el usuario coloca el archivo); no lee FBX/OBJ/GLB; no mide tris/texturas ni presupuestos; no exporta a Unity; no guarda origen/licencia | Gratis, dentro de Blender. Fuente: https://docs.blender.org/manual/es/3.4/files/asset_libraries/introduction.html |
| **LocalFab** | Lo más parecido en concepto: gestor nativo local-first, indexa carpetas, vista previa sin abrir Blender, exporta carpetas limpias a Unreal/Unity/Blender, sin nube ni cuenta; OBJ/FBX/GLTF/GLB/STL/DAE/USDA | **Solo macOS; de pago ($49 early access / $59 lanzamiento); aún en early access/waitlist** (10/12 hitos, DMG en empaquetado); sin presupuestos VRChat, sin semáforo PC/Quest, sin manifiesto de licencia, sin .blend | $49/$59 pago único; macOS only. Fuente: https://www.localfab.app/ |
| **Oddments** (MIT, 2026) | Librería local-first de referencias (imágenes, vídeo, fuentes, PDF, 3D) para Windows/macOS; visor 3D GLB/OBJ/FBX/STL/USDZ + previews .blend vía Blender instalado; búsqueda semántica por IA local; plugins Blender/Figma; sin cuenta ni telemetría | Es una **librería de referencias**, no de assets de producción VRChat: sin medición de tris/materiales/texturas, sin presupuestos ni semáforo VRChat, sin export a Unity con manifiesto, sin detección de duplicados orientada a producción | Gratis, MIT, Windows/macOS. Fuentes: https://github.com/peopleskynet-boop/Oddments , https://www.producthunt.com/products/oddments |
| **MeshyLib** | Add-on Blender ($24) que convierte carpetas propias en librería con miniaturas e inserción en un clic + caja de herramientas de limpieza; Live Link al Asset Browser | **Solo dentro de Blender**, de pago, sin standalone, sin Unity, sin presupuestos VRChat | $24; Blender 4.5+. Fuente: https://superhivemarket.com/products/meshylib---your-private-asset-browser-?search_id=50457559 |
| **VCC (VRChat Creator Companion)** | Gestor oficial de proyectos Unity + paquetes SDK vía VPM + plantillas + versión correcta de Unity | No es gestor de assets: sin búsqueda/tags/preview fuera de Unity, sin ficha de asset, sin presupuestos antes de importar (el SDK solo informa tras construir), sin licencias | Gratis, oficial. Fuente: https://www.vrcreators.net/docs/vrchat/setting-up-vrchat-creator-companion |
| **VRWorld Toolkit** (Unity, curado por VRChat) | Debugger de mundo con 90+ checks, informe de tamaño del build, Mass Texture Importer, post-procesado en un clic | **Solo dentro de Unity y por escena/proyecto, tras importar**; no es librería entre carpetas/proyectos; sin triaje previo, sin duplicados en disco, sin manifiesto de licencia | Gratis, open source (Unity). Fuentes: https://vpm-catalog.vercel.app/packages/dev.onevr.vrworldtoolkit/ , https://ask.vrchat.com/t/vrworld-toolkit/1423 |
| **EasyQuestSwitch** (Unity, curado) | Automatiza cambios PC↔Android (shaders etc.) al cambiar de plataforma | Solo conmutación dentro de Unity por escena; no librería, no presupuestos, no export | Gratis, open source. Fuente: https://vcc.docs.vrchat.com/vpm/curated-community-packages/ |
| **Assets Manager for VRChat** (AlanBacker, MIT, v1.1.5) | **El competidor directo más cercano:** librería dentro de Unity para prefabs de Booth/Gumroad; grupos/carpetas, portadas, apodos, enlaces a tienda, notas, tags, búsqueda instantánea | **Solo dentro de Unity y por proyecto** (`library.json` en ProjectSettings); sin medición de tris/texturas ni semáforo VRChat; sin indexar FBX/OBJ/GLB/.blend en disco fuera de Unity; sin export con manifiesto | Gratis, MIT, plugin Unity. Fuente: https://vpm-catalog.vercel.app/packages/com.alanbacker.assets-manager-for-vrchat/ |
| **Meshory / My3DLibrary** | Gestores locales con miniaturas, visor 3D y detección de duplicados por geometría (incluso en ZIP) | Orientados a **impresión 3D** (STL/3MF); de pago o beta; sin presupuestos VRChat ni export a Unity | Meshory de pago; My3DLibrary beta gratis. Fuentes: https://meshory.com/features , https://ko-fi.com/s/10800812f6 |

**El hueco, en una frase:** nadie combina (a) standalone en Windows, gratis y open source, (b) indexación de archivos propios FBX/OBJ/GLB/.blend en disco con vista previa sin abrir Blender/Unity, (c) ficha medida por asset con semáforo doble PC/Quest basado en las cifras oficiales, (d) presupuesto agregado por colección/mundo, (e) detección de duplicados y (f) export limpio a Unity con manifiesto de origen/licencia. LocalFab hace (a–b) en Mac y de pago; Assets Manager hace parte de (b) dentro de Unity y por proyecto; VRWorld Toolkit hace validación (c) parcial dentro de Unity y tras importar. El Vault es el único que lo hace **antes** de Unity, en Windows, gratis.

---

## 5. Recomendaciones de producto derivadas (priorizadas)

1. **Ficha por asset con semáforo doble PC/Quest desde el día 1:** tris, nº de meshes/submeshes, materiales, texturas (dimensión máx. + memoria estimada), tamaño de archivo. Umbrales por defecto desde §3 (Quest: 250k mundo / 1024px / 100 MB; PC: 200 MB orientativo). Que los umbrales sean configurables y etiquetar los no oficiales como tales.
2. **Presupuesto agregado por colección/mundo:** suma de tris/materiales/texturas/tamaño de los assets seleccionados, con barra contra 250k tris y 100 MB Quest. Es la función que responde a N2 y N8; sin ella la ficha aislada engaña.
3. **Vista previa + búsqueda/tags/colecciones por mundo sin abrir Blender/Unity:** el núcleo de N3; incluir miniaturas.
4. **Detección de duplicados** (por hash y, si es viable, por geometría/nombre) y detección de archivos rotos o sin texturas: varias guías citan texturas duplicadas de paquetes importados como causa de mundo inflado.
5. **Export a Unity con manifiesto** (origen, autor, URL, licencia, fecha) y carpeta limpia modelo+texturas: responde a N4 y N6; no redistribuir nada que no sea del usuario.
6. **Avisos de import en la ficha:** escala/unidades sospechosas, material sin textura, shader no móvil, textura >1024px, audio pesado. Checklist previa al import, no auditoría posterior.
7. **No prometer lo que es de Unity:** la validación final (draw calls reales, lightmaps, occlusion, espejos, 45 FPS) sigue siendo del SDK/VRWorld Toolkit/Profiler. El Vault es triaje previo, no sustituto del SDK. Decirlo así en el README evita sobreventa.
8. **No incluir:** tienda de assets, descarga de modelos de terceros, ni gestión de proyectos VCC (eso ya lo hace VCC). Mantener el foco estrecho VRChat-en-Windows.
