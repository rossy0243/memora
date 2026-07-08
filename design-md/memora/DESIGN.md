---
version: alpha
name: Memora
description: A mobile-first event memory platform that feels premium, emotional, and extremely simple. The guest experience is photo-first and action-led: scan, capture, choose the moment, send. Organizer surfaces are calmer and more operational, with clean metrics, public link sharing, QR code access, and media management.

colors:
  primary: "#9f4f5f"
  primary-active: "#7f3948"
  primary-soft: "#f4d9d5"
  ink: "#241f22"
  body: "#4f464a"
  muted: "#746a6e"
  hairline: "#eadfda"
  canvas: "#fffaf7"
  surface: "#ffffff"
  surface-soft: "#f7efeb"
  sage: "#dfe7dd"
  champagne: "#d8b46a"
  success: "#2f7d5b"
  warning: "#b7791f"
  error: "#b94242"
  on-primary: "#ffffff"
  on-dark: "#ffffff"

typography:
  display-xl:
    fontFamily: "Playfair Display, Georgia, serif"
    fontSize: 64px
    fontWeight: 700
    lineHeight: 0.96
    letterSpacing: 0
  display-lg:
    fontFamily: "Playfair Display, Georgia, serif"
    fontSize: 44px
    fontWeight: 700
    lineHeight: 1.04
    letterSpacing: 0
  display-md:
    fontFamily: "Playfair Display, Georgia, serif"
    fontSize: 32px
    fontWeight: 700
    lineHeight: 1.12
    letterSpacing: 0
  title-lg:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: 22px
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: 0
  title-md:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: 18px
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: 0
  body-lg:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: 18px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  body-md:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: 0
  body-sm:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.45
    letterSpacing: 0
  button:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: 16px
    fontWeight: 700
    lineHeight: 1
    letterSpacing: 0
  caption:
    fontFamily: "Inter, system-ui, sans-serif"
    fontSize: 13px
    fontWeight: 500
    lineHeight: 1.35
    letterSpacing: 0

rounded:
  none: 0px
  sm: 6px
  md: 8px
  lg: 12px
  xl: 16px
  pill: 9999px
  full: 9999px

spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px
  section: 72px

components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 16px 22px
    minHeight: 56px
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.button}"
    rounded: "{rounded.md}"
    padding: 15px 21px
    minHeight: 54px
  guest-hero:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.display-lg}"
    rounded: "{rounded.none}"
    padding: 24px
  capture-panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.lg}"
    padding: 20px
  moment-chip:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.pill}"
    padding: 12px 16px
  moment-chip-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.on-dark}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.pill}"
  media-card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.md}"
  dashboard-stat:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.title-md}"
    rounded: "{rounded.md}"
    padding: 18px
  dashboard-table-row:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.body}"
    typography: "{typography.body-sm}"
    rounded: "{rounded.none}"
  public-link-card:
    backgroundColor: "{colors.surface-soft}"
    textColor: "{colors.ink}"
    typography: "{typography.body-md}"
    rounded: "{rounded.md}"
    padding: 16px
---

## Vision

Memora doit donner une impression de souvenir prive, pas de logiciel technique. La page invite doit etre presque invisible : une belle image, le nom de l'evenement, un message court, un gros bouton. L'interface organisateur peut etre plus dense, mais elle doit rester calme et lisible.

La promesse d'usage reste :

1. Scanner
2. Filmer ou photographier
3. Choisir le moment
4. Envoyer

## Direction retenue

### Ce que l'on reprend

- D'Apple : le calme, la respiration, les surfaces qui laissent les photos parler.
- D'Airbnb : le cote humain, accessible, avec des actions tres visibles sur mobile.
- De Pinterest : la logique de galerie media, avec des images comme element central.
- De Cal.com : la clarte des pages organisateur et des controles fonctionnels.

### Ce que l'on evite

- Trop de beige ou de rose partout.
- Les grosses pages marketing avant le produit.
- Les cartes imbriquees.
- Les gradients decoratifs, les effets lourds et les ombres excessives.
- Les petits boutons difficiles a toucher sur mobile.

## Experience invite

La page invite est mobile-first et photo-first.

Le premier ecran doit contenir :

- l'image ou la banniere de l'evenement ;
- le nom de l'evenement ;
- un message d'accueil court ;
- un bouton principal "Ajouter un souvenir".

Le bouton principal doit avoir une hauteur minimale de 56px. Les categories de moment doivent etre affichees sous forme de grands chips tactiles, avec une selection evidente.

L'invite ne doit jamais voir une interface de dashboard, de compte ou de reglage.

## Experience organisateur

Le dashboard doit etre plus sobre :

- stats simples en haut ;
- lien public et QR code visibles ;
- derniers medias sous forme de grille ;
- bouton ZIP tres clair ;
- statut de l'evenement et retention affiches sans bruit.

Les surfaces organisateur doivent utiliser plus de blanc, de lignes fines et de composants compacts que la page invite.

## Palette

La palette doit rester douce, mais pas monochrome :

- rose profond pour l'action principale ;
- papier chaud pour le fond public ;
- blanc pour les surfaces fonctionnelles ;
- sauge pour les touches secondaires ;
- champagne uniquement comme accent rare.

Le rose principal ne doit pas devenir decoratif. Il sert aux actions importantes.

## Typographie

Memora utilise deux voix :

- Playfair Display pour l'emotion, les titres et le nom de marque ;
- Inter pour les interfaces, formulaires, boutons et textes courts.

Les textes doivent rester courts. Le produit doit se comprendre par la disposition et les actions, pas par de longues explications.

## Regles mobile-first

- Largeur confortable sur 320px.
- Aucun bouton principal sous 54px de hauteur.
- Une seule action dominante par ecran.
- Les medias et les boutons passent avant le texte long.
- Les formulaires invites doivent rester en une colonne.

## Prochaine application

Quand ce guide est valide, appliquer la direction a :

1. la landing actuelle ;
2. les futurs ecrans de creation d'evenement ;
3. la page publique `/e/<slug>/` ;
4. le dashboard organisateur.
