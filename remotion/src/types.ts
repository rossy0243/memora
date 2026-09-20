// Contrat entre Django et Remotion : Django produit ce JSON, Remotion le rend.
// Toute evolution ici doit rester alignee avec le builder cote Python.

export type ClipKind = "image" | "video";

export interface FilmClip {
  kind: ClipKind;
  // Chemin local (staticFile) ou URL. Django fournit des chemins locaux au rendu.
  src: string;
  durationInFrames: number;
  // Code du moment (ceremony, dancefloor...) : sert a regrouper les plans.
  category?: string;
  // Libelle humain accentue du moment (« Cérémonie », « Cocktail »…), fourni par
  // Django. Affiche en lower-third sur le premier plan de chaque moment.
  label?: string;
  // Garder le son du plan (voix des invites). Django ne l'active que sur les
  // videos avec voix, pour le heros et l'integrale — jamais sur le teaser.
  // La musique est automatiquement duckee pendant ces passages.
  keepAudio?: boolean;
  // Multiplicateur CSS brightness() : corrige une exposition mesuree trop
  // sombre/cramee (processing.analysis), sans toucher a l'accord colorimetrique.
  // Absent ou 1 = pas de correction.
  brightnessCorrection?: number;
}

// Photo utilisee dans le mini-collage de fin (voir HighlightCollage.tsx) — un
// sous-ensemble de FilmClip : pas de duree/keepAudio propres, la collage a sa
// propre duree globale et n'a jamais de son.
export interface HighlightClip {
  kind: ClipKind;
  src: string;
}

// Chiffres de participation reels de l'evenement, pour le carton recap.
export interface FilmStats {
  totalMemories: number;
  contributors: number;
}

export interface FilmProps {
  clips: FilmClip[];
  // Piste musicale (chemin local). Optionnelle : sans musique, on garde le son des clips.
  audioSrc: string | null;
  // Decalage du premier temps fort de la musique, en secondes.
  audioFirstBeatOffset: number;
  title: string;
  subtitle: string;
  outroTitle: string;
  // Duree des cartons, en frames.
  introDurationInFrames: number;
  outroDurationInFrames: number;
  // Duree d'une transition entre plans, en frames.
  transitionDurationInFrames: number;
  // Look colorimetrique (accord chaud pour les mariages).
  grade: "romantic" | "warm" | "neutral";
  // Rythme par format : le teaser est punchy (Ken Burns marque), l'integrale
  // respire (mouvement plus calme). Le heros est equilibre.
  pace: "punchy" | "balanced" | "gentle";
  // Volume de la musique, et volume reduit (ducking) quand un plan garde la
  // voix des invites (keepAudio). Alignes sur les reglages du pipeline FFmpeg.
  musicVolume: number;
  duckedMusicVolume: number;
  // Bandeaux cinema (2.35:1) : reserves au heros, l'effet "salle de cinema".
  // Absent (undefined) = pas de bandeaux, comme avant.
  cinematicBars?: boolean;
  // Watermark permanent (coin bas-droit) : reserve au teaser, le format que les
  // invites partagent — la marque doit y rester visible du debut a la fin.
  watermark?: boolean;
  // Index (dans `clips`) du plan choisi pour l'ouverture a froid — le mieux note
  // (processing.analysis), pas forcement le premier chronologique. Absent = 0.
  coldOpenClipIndex?: number;
  // Mot des maries : carton juste apres l'intro. Vide = carton saute (jamais sur
  // le Teaser, voir processing.remotion.build_film_props).
  welcomeMessage?: string;
  welcomeMessageDurationInFrames?: number;
  // Recap en chiffres (participation reelle de l'evenement) avant la sortie.
  // null/absent = carton saute.
  stats?: FilmStats | null;
  statsDurationInFrames?: number;
  // Mini-collage des meilleurs moments festifs, juste avant le recap/la sortie.
  // Tableau vide = pas de collage (moins de 2 candidats trouves cote Python).
  highlightClips?: HighlightClip[];
  highlightDurationInFrames?: number;
}

// --- Cartons du livre d'or ---------------------------------------------------
// Le montage du livre d'or est assemble par FFmpeg (voir
// processing/guestbook_montage.py) ; Remotion ne dessine que ses cartons, en
// images fixes.

// Carton du livre d'or rendu en image fixe (voir GuestBookCard.tsx).
export interface GuestBookCardProps {
  kind: "intro" | "name" | "outro";
  title: string;
  subtitle: string;
  name: string;
  // Sert uniquement a caler les animations du carton : l'image est prise a un
  // instant precis (`renderStill --frame`), pas jouee sur cette duree.
  durationInFrames: number;
}

export const defaultGuestBookCardProps: GuestBookCardProps = {
  kind: "name",
  title: "Livre d'or",
  subtitle: "",
  name: "Camille",
  durationInFrames: 90,
};

export const defaultFilmProps: FilmProps = {
  clips: [],
  audioSrc: null,
  audioFirstBeatOffset: 0,
  title: "Camille & Noé",
  subtitle: "12/07/2026",
  outroTitle: "Merci",
  introDurationInFrames: 90,
  outroDurationInFrames: 120,
  transitionDurationInFrames: 15,
  grade: "romantic",
  pace: "balanced",
  musicVolume: 0.85,
  duckedMusicVolume: 0.25,
  cinematicBars: false,
  watermark: false,
  coldOpenClipIndex: 0,
  welcomeMessage: "",
  welcomeMessageDurationInFrames: 150,
  stats: null,
  statsDurationInFrames: 120,
  highlightClips: [],
  highlightDurationInFrames: 120,
};
