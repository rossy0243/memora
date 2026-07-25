import React from "react";
import {
  AbsoluteFill,
  Audio,
  interpolate,
  staticFile,
  useVideoConfig,
} from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { FilmProps } from "./types";
import { Clip } from "./Clip";
import { TitleCard } from "./TitleCard";

function resolveSrc(src: string): string {
  return /^https?:\/\//.test(src) ? src : staticFile(src);
}

// Le film complet : carton d'ouverture -> plans en fondus enchaines -> carton de fin,
// avec une piste musicale par-dessus. Les fondus (fade) sont le choix le plus sobre ;
// le rythme vient de la duree des plans, calee sur le tempo cote Django.
export const MemoraFilm: React.FC<FilmProps> = (props) => {
  const {
    clips,
    audioSrc,
    audioFirstBeatOffset,
    title,
    subtitle,
    outroTitle,
    introDurationInFrames,
    outroDurationInFrames,
    transitionDurationInFrames,
    grade,
    pace,
    musicVolume,
    duckedMusicVolume,
  } = props;
  const { fps } = useVideoConfig();

  const transition = () => (
    <TransitionSeries.Transition
      presentation={fade()}
      timing={linearTiming({ durationInFrames: transitionDurationInFrames })}
    />
  );

  // Le lower-third (nom du moment) ne s'affiche que sur le PREMIER plan de chaque
  // moment : il marque l'entree dans un nouveau chapitre (Cérémonie, Soirée…)
  // sans repeter le libelle sur chaque photo.
  const seenLabels = new Set<string>();
  const clipLabels = clips.map((clip) => {
    const label = clip.label?.trim();
    if (!label || seenLabels.has(label)) return undefined;
    seenLabels.add(label);
    return label;
  });

  // Segments [debut, fin] (en frames) des plans qui gardent la voix des invites.
  // Dans une TransitionSeries, chaque transition CHEVAUCHE les deux sequences :
  // le plan i commence donc a (somme des durees precedentes) - (i+1) transitions.
  const voiceSegments: Array<[number, number]> = [];
  let clipStart = introDurationInFrames - transitionDurationInFrames;
  for (const clip of clips) {
    if (clip.keepAudio) {
      voiceSegments.push([clipStart, clipStart + clip.durationInFrames]);
    }
    clipStart += clip.durationInFrames - transitionDurationInFrames;
  }

  // Ducking : la musique descend a duckedMusicVolume pendant les passages avec
  // voix, avec une rampe douce d'un tiers de seconde de part et d'autre.
  const ramp = Math.max(Math.round(fps / 3), 1);
  const musicVolumeAt = (frame: number): number => {
    let volume = musicVolume;
    for (const [start, end] of voiceSegments) {
      const dip = interpolate(
        frame,
        [start - ramp, start, end, end + ramp],
        [musicVolume, duckedMusicVolume, duckedMusicVolume, musicVolume],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
      );
      volume = Math.min(volume, dip);
    }
    return volume;
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f0c0d" }}>
      <TransitionSeries>
        <TransitionSeries.Sequence durationInFrames={introDurationInFrames}>
          <TitleCard
            title={title}
            subtitle={subtitle}
            durationInFrames={introDurationInFrames}
          />
        </TransitionSeries.Sequence>

        {clips.flatMap((clip, index) => [
          transition(),
          <TransitionSeries.Sequence
            key={`clip-${index}`}
            durationInFrames={clip.durationInFrames}
          >
            <Clip clip={clip} grade={grade} pace={pace} chapterLabel={clipLabels[index]} />
          </TransitionSeries.Sequence>,
        ])}

        {transition()}
        <TransitionSeries.Sequence durationInFrames={outroDurationInFrames}>
          <TitleCard
            title={outroTitle}
            subtitle={title}
            durationInFrames={outroDurationInFrames}
          />
        </TransitionSeries.Sequence>
      </TransitionSeries>

      {audioSrc ? (
        <Audio
          src={resolveSrc(audioSrc)}
          startFrom={Math.round(audioFirstBeatOffset * fps)}
          volume={musicVolumeAt}
        />
      ) : null}
    </AbsoluteFill>
  );
};
