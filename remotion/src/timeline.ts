import { FilmClip, FilmProps } from "./types";

// Ouverture a froid (voir MemoraFilm.tsx) : avec au moins deux plans, l'un
// d'eux (coldOpenClipIndex, cote Python le mieux note) sert de fond muet au
// carton d'intro et ne repasse pas dans le montage principal — sa duree est
// deja comptee via introDurationInFrames. Duree et rendu DOIVENT utiliser
// exactement cette meme regle : sinon la composition annonce une longueur qui
// ne correspond plus a ce que la TransitionSeries produit reellement (queue
// figee ou coupee en fin de rendu).
export function usesColdOpen(clips: FilmClip[]): boolean {
  return clips.length > 1;
}

export function coldOpenIndex(clips: FilmClip[], requestedIndex?: number): number {
  if (!usesColdOpen(clips)) return -1;
  const index = requestedIndex ?? 0;
  return index >= 0 && index < clips.length ? index : 0;
}

export function mainClips(clips: FilmClip[], requestedIndex?: number): FilmClip[] {
  const index = coldOpenIndex(clips, requestedIndex);
  if (index < 0) return clips;
  return clips.filter((_, i) => i !== index);
}

// Duree totale = intro + somme des segments - recouvrements des transitions.
// Chaque transition mange `transitionDurationInFrames` a la jonction de deux
// segments. Les cartons additionnels (mot des maries, collage, recap en
// chiffres) ne comptent que s'ils sont effectivement rendus par MemoraFilm —
// meme condition ici et cote composant, sinon meme bug que pour l'ouverture a
// froid (duree annoncee qui ne correspond plus au rendu reel).
export function totalDurationInFrames(props: FilmProps): number {
  const {
    clips,
    introDurationInFrames,
    outroDurationInFrames,
    transitionDurationInFrames,
    coldOpenClipIndex,
    welcomeMessage,
    welcomeMessageDurationInFrames,
    highlightClips,
    highlightDurationInFrames,
    stats,
    statsDurationInFrames,
  } = props;

  const segments = [introDurationInFrames];
  if (welcomeMessage) {
    segments.push(welcomeMessageDurationInFrames ?? 0);
  }
  segments.push(...mainClips(clips, coldOpenClipIndex).map((c) => c.durationInFrames));
  if (highlightClips && highlightClips.length >= 2) {
    segments.push(highlightDurationInFrames ?? 0);
  }
  if (stats) {
    segments.push(statsDurationInFrames ?? 0);
  }
  segments.push(outroDurationInFrames);

  const sum = segments.reduce((a, b) => a + b, 0);
  const junctions = Math.max(segments.length - 1, 0);
  const total = sum - junctions * transitionDurationInFrames;
  return Math.max(total, 1);
}
