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
}

// --- Montage du livre d'or ---------------------------------------------------
// Livrable distinct : tous les messages video en entier, dans l'ordre, chacun
// precede d'un carton plein ecran « De la part de … ». Django fournit les clips
// deja ordonnes chronologiquement.

export interface GuestBookMessageClip {
  // Chemin local (staticFile) du message video.
  src: string;
  durationInFrames: number;
  // Nom saisi par l'agent avant l'enregistrement. Vide = message anonyme.
  guestName: string;
}

export interface GuestBookProps {
  messages: GuestBookMessageClip[];
  audioSrc: string | null;
  audioFirstBeatOffset: number;
  title: string;
  subtitle: string;
  outroTitle: string;
  introDurationInFrames: number;
  outroDurationInFrames: number;
  nameCardDurationInFrames: number;
  transitionDurationInFrames: number;
  grade: "romantic" | "warm" | "neutral";
  // Lit musical discret ; descend encore (ducked) pendant chaque message.
  musicVolume: number;
  duckedMusicVolume: number;
}

export const defaultGuestBookProps: GuestBookProps = {
  messages: [],
  audioSrc: null,
  audioFirstBeatOffset: 0,
  title: "Livre d'or",
  subtitle: "Vos messages",
  outroTitle: "Merci à tous",
  introDurationInFrames: 150,
  outroDurationInFrames: 180,
  nameCardDurationInFrames: 90,
  transitionDurationInFrames: 15,
  grade: "warm",
  musicVolume: 0.12,
  duckedMusicVolume: 0.04,
};

export function guestBookTotalDurationInFrames(props: GuestBookProps): number {
  const segments = [
    props.introDurationInFrames,
    ...props.messages.flatMap((m) => [
      props.nameCardDurationInFrames,
      m.durationInFrames,
    ]),
    props.outroDurationInFrames,
  ];
  const sum = segments.reduce((a, b) => a + b, 0);
  const junctions = Math.max(segments.length - 1, 0);
  return Math.max(sum - junctions * props.transitionDurationInFrames, 1);
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
  musicVolume: 0.85,
  duckedMusicVolume: 0.25,
};
