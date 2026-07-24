import { FilmProps } from "./types";

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
    ...clips.map((c) => c.durationInFrames),
    outroDurationInFrames,
  ];

  const sum = segments.reduce((a, b) => a + b, 0);
  const junctions = Math.max(segments.length - 1, 0);
  const total = sum - junctions * transitionDurationInFrames;
  return Math.max(total, 1);
}
