# Rendu premium des films Memora avec Remotion

Ce dossier contient le pipeline de rendu vidéo **Remotion** de Memora, sur la branche
`remotion-premium-render`. L'objectif : produire les **trois livrables** (film héros,
intégrale, teaser vertical) au niveau **ultra premium** — cartons animés, transitions,
Ken Burns, grade colorimétrique cohérent et lit musical — ce qu'un graphe de filtres
FFmpeg ne sait pas exprimer proprement.

> **Statut** : Phase 1 terminée (le pipeline rend de vrais MP4). Phases 2 et 3 à venir.

---

## Pourquoi Remotion (et le contexte de la décision)

Le pipeline historique assemble les films en **FFmpeg pur** (`processing/services.py`).
Il fonctionne, et il reste la référence sur `main`. Mais son plafond « motion design »
est limité : pas de vraies transitions animées, pas de typographie cinétique.

- Comparaison faite avec **HyperFrames** (HeyGen, Apache 2.0, HTML→vidéo). J'avais
  recommandé HyperFrames pour sa licence libre.
- Le propriétaire a **choisi Remotion** en connaissance du coût de licence commerciale.
  Cette branche applique ce choix.

**Architecture retenue** : Remotion **possède tout le rendu** (clips + transitions +
titres + couleur + musique), et non un simple habillage par-dessus FFmpeg. Les clips
invités sont intégrés via `<OffthreadVideo>` (extraction de frames par FFmpeg, pas de
lecture temps réel), ce qui garde le coût raisonnable.

---

## FFmpeg n'est PAS supprimé — il garde un rôle central

« Remotion vs FFmpeg » est un faux dilemme. Remotion décrit la *composition* (React) ;
tout le travail vidéo lourd reste fait par FFmpeg. Adopter Remotion **n'élimine pas
FFmpeg**. Il intervient à quatre endroits :

1. **À l'intérieur de Remotion.** `<OffthreadVideo>` extrait les frames des clips via
   FFmpeg, et l'encodage final (frames + audio → MP4) se fait via FFmpeg. Remotion
   embarque son propre binaire (`@remotion/renderer`). Les MP4 rendus en phase 1 ont
   donc été **encodés par FFmpeg, piloté par Remotion**.
2. **Filet de sécurité / fallback.** Le pipeline FFmpeg Python historique
   (`processing/services.py`) reste **actif en production** tant que le feature flag
   `MEMORA_MOVIE_RENDER_PROVIDER` n'est pas basculé sur `remotion`, et sert de repli si
   Remotion échoue. Il n'est pas supprimé.
3. **Usages indépendants du rendu.** Mesure de tempo (`processing/tempo.py`), analyse
   média, `ffprobe`, archive ZIP — toujours FFmpeg/ffprobe, inchangés.
4. **Rôle hybride probable (phase 2/3).** Le **ducking audio** (baisser la musique sous
   les voix des invités, via `sidechaincompress`) se fait mal dans Remotion. Le scénario
   propre sera sans doute **Remotion pour le visuel + une passe FFmpeg finale pour le
   mixage audio**, surtout sur le héros et l'intégrale où l'on garde la voix des invités.

En résumé : FFmpeg devient (a) le moteur d'encodage **sous** Remotion, (b) le pipeline
de secours, (c) l'outil de mesure/analyse, (d) probablement le mixeur audio final.
C'est une couche de design **par-dessus** FFmpeg, pas un remplacement.

---

## Ce qui a été fait — Phase 1 (terminée)

Scaffold Remotion complet + preuve de rendu de bout en bout.

### Structure du projet

```
remotion/
├── package.json            # Remotion 4.0.498, React 19
├── tsconfig.json
├── remotion.config.ts      # H.264, CRF 18, rendu déterministe
├── render-props.example.json  # props d'exemple (médias de test)
├── src/
│   ├── index.ts            # registerRoot
│   ├── Root.tsx            # 3 compositions : Teaser, Hero, Full
│   ├── types.ts            # FilmProps = contrat Django → Remotion
│   ├── timeline.ts         # calcul de la durée totale
│   ├── MemoraFilm.tsx      # composition principale (TransitionSeries + Audio)
│   ├── Clip.tsx            # un plan : Ken Burns + fond flouté + grade + vignette
│   ├── TitleCard.tsx       # carton animé (intro / outro)
│   └── grade.ts            # accords colorimétriques (romantic / warm / neutral)
└── public/sample/          # médias de test (gitignored)
```

### Le contrat Django → Remotion (`src/types.ts`)

Django produit un JSON `FilmProps`, Remotion le rend. **Toute évolution de ce type doit
rester alignée avec le builder Python** (à créer en phase 2).

Champs : `clips[]` (kind image/video, src, durationInFrames, category), `audioSrc`,
`audioFirstBeatOffset`, `title`, `subtitle`, `outroTitle`, durées des cartons et des
transitions, `grade`.

### Une seule composition, trois formats

`MemoraFilm` est paramétrée par dimensions. `Root.tsx` en dérive :

| Composition | Dimensions | Usage |
|---|---|---|
| `Teaser` | 1080×1920 | teaser vertical (partage mobile) |
| `Hero`   | 1920×1080 | film héros |
| `Full`   | 1920×1080 | intégrale |

La durée totale est calculée par `calculateMetadata` (somme des plans − recouvrement
des transitions).

### Éléments premium en place

- **Carton animé** : titre qui monte et se révèle, filet doré qui se trace, fondu de
  sortie (`TitleCard.tsx`).
- **Fond flouté plein cadre** : un plan dont le ratio ne colle pas au format est
  contenu au centre sur une version floutée de lui-même — pas de bandes noires
  (même principe que le pipeline FFmpeg).
- **Ken Burns** : zoom lent continu sur chaque plan.
- **Grade** : accord chaud/doux/pellicule, cohérent d'un plan à l'autre (CSS filter),
  ce qui manquait au grade FFmpeg (teinte uniforme non harmonisée).
- **Vignette** douce.
- **Transitions** : fondus enchaînés (`@remotion/transitions`).
- **Musique** : lit musical démarré sur le premier temps fort (`audioFirstBeatOffset`).

### Preuve

Rendu vérifié en sondant les MP4 et en lisant des images extraites (pas au code seul) :

- **Teaser** → 1080×1920, 30 fps, H.264 + AAC, cartons animés, fond flouté, grade,
  transitions, musique. ✓
- **Hero** → 1920×1080, mêmes éléments. ✓

> ⚠️ Le test utilise des **dégradés**, pas de vraies photos. La *mécanique* premium est
> prouvée ; le *ressenti émotionnel* sur du vrai contenu ne se jugera qu'en phase 3.

---

## Comment lancer en local

```bash
cd remotion
npm install            # Remotion + un Chrome headless au 1er rendu
npm run dev            # Remotion Studio (aperçu interactif)

# Rendre un format avec les props d'exemple :
npx remotion render Teaser out/teaser.mp4 --props=render-props.example.json
npx remotion render Hero   out/hero.mp4   --props=render-props.example.json
```

> Note npm 11 : le postinstall d'`esbuild` est bloqué par la politique `allow-scripts`,
> mais Remotion 4.x fournit le binaire via `@esbuild/<platform>` — l'install reste
> fonctionnelle. En cas de doute : `npm install --foreground-scripts`.

---

## La suite — Phase 2 : intégration Django (à venir)

Objectif : Django orchestre, Remotion rend.

1. **Builder EDL** (Python) : réutiliser la logique existante de `processing/services.py`
   et `processing/soundtrack.py` (sélection, ordre narratif, calage tempo) pour produire
   le JSON `FilmProps` au lieu de piloter FFmpeg. **Garder l'alignement avec `types.ts`.**
2. **Assets locaux** : télécharger les clips sélectionnés et la piste musicale depuis R2
   vers un dossier temporaire (les mettre dans `public/` ou passer des chemins absolus),
   car Remotion/Chrome lit des fichiers locaux.
3. **Déclenchement du rendu** : appeler Remotion via l'API `@remotion/renderer`
   (Node) — `bundle()` + `renderMedia()` — plutôt que la CLI, pour un contrôle propre
   des props et du chemin de sortie. Un petit script Node `render.mjs` prend le JSON en
   entrée et écrit le MP4.
4. **Orchestration** : le worker Python appelle ce script Node en sous-processus (comme
   il appelle déjà FFmpeg), récupère le MP4, le stocke sur R2 (`final_file` / `full_file`
   / `teaser_file`).
5. **Feature flag** : `MEMORA_MOVIE_RENDER_PROVIDER` existe déjà (`ffmpeg` / `runway`).
   Ajouter `remotion` et **basculer par variable d'environnement**, pour comparer côte à
   côte sans casser le pipeline FFmpeg qui reste le filet de sécurité.

### ⚠️ Enjeu d'infra à anticiper (le vrai coût du choix Remotion)

Le worker de rendu est **Python** aujourd'hui. Faire tourner Remotion demande :

- **Node 18+** et le **Chrome headless de Remotion** dans l'image Docker du worker
  (plusieurs centaines de Mo de plus).
- Une **instance worker plus costaude** (Chrome + rendu frame par frame = plus de
  CPU/RAM que le concat FFmpeg).
- Décider où tournent les `npm install` / le bundle : au build de l'image (recommandé,
  pour un démarrage rapide) plutôt qu'au runtime.
- Alternative à évaluer si l'infra locale devient trop lourde : **Remotion Lambda**
  (rendu déporté sur AWS), au prix d'une dépendance cloud supplémentaire.

Le rendu reste **asynchrone** (films générés à J+1 midi via la file), donc la lenteur
relative de Chrome n'est pas bloquante — un pic de festivités est absorbé par la file.

---

## Phase 3 : polish ultra premium des 3 formats (à venir)

Une fois l'intégration branchée et un vrai film de mariage rendu :

- Calibrer les durées, transitions et grade **par format** (le teaser est punchy et
  court ; l'intégrale respire).
- Enrichir la typographie (polices premium chargées dans Remotion via `@remotion/google-fonts`
  ou des `.ttf` locaux, au lieu de Georgia système).
- Décider du **son des invités** : lit musical seul (teaser) vs. musique + voix des
  invités avec ducking (héros/intégrale) — le ducking se fait au montage audio FFmpeg
  final ou dans Remotion.
- Éventuels **lower-thirds** (prénoms/rôles) et cartons de chapitre par moment
  (cérémonie, soirée…).

---

## Principes à respecter dans cette branche

- **Le pipeline FFmpeg reste la référence sur `main`.** Ne pas le supprimer tant que
  Remotion n'est pas prouvé sur de vrais films en production ; garder le feature flag.
- **`types.ts` est le contrat.** Toute modif d'un côté (Python builder / TSX) doit être
  répercutée de l'autre.
- **Vérifier par le rendu, pas par le code.** Sonder les MP4, regarder les images —
  c'est comme ça que la phase 1 a été validée.
- **Ne jamais laisser une variante casser le film principal** (principe déjà en place
  côté FFmpeg) : le rendu Remotion doit échouer proprement et, à terme, pouvoir
  retomber sur FFmpeg.
