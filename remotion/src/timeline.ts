import { FilmClip, FilmProps } from "./types";

// Ouverture a froid (voir MemoraFilm.tsx) : avec au moins deux plans, le premier
// sert de fond muet au carton d'intro et ne repasse pas dans le montage
// principal — sa duree est deja comptee via introDurationInFrames. Duree et
// rendu DOIVENT utiliser exactement cette meme regle : sinon la composition
// annonce une longueur qui ne correspond plus a ce que la TransitionSeries
// produit reellement (queue figee ou coupee en fin de rendu).
export function usesColdOpen(clips: FilmClip[]): boolean {
  return clips.length > 1;
}

export function mainClips(clips: FilmClip[]): FilmClip[] {
  return usesColdOpen(clips) ? clips.slice(1) : clips;
}

// Duree totale = intro + somme des clips - recouvrements des transitions + outro.
// Chaque transition mange `transitionDurationInFrames` a la jonction de deux plans.
// Cartons inclus : intro->clip1 et clipN->outro sont aussi des transitions.
export function totalDurationInFrames(props: FilmProps): number {
  const {
    clips,
    introDurationInFrames,
    outroDurationInFrames,
    transitionDurationInFrames,
  } = props;

  const segments = [
    introDurationInFrames,
    ...mainClips(clips).map((c) => c.durationInFrames),
    outroDurationInFrames,
  ];

  const sum = segments.reduce((a, b) => a + b, 0);
  const junctions = Math.max(segments.length - 1, 0);
  const total = sum - junctions * transitionDurationInFrames;
  return Math.max(total, 1);
}
