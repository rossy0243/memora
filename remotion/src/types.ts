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
}

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
};
