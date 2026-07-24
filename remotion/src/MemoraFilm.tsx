import React from "react";
import { AbsoluteFill, Audio, staticFile } from "remotion";
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
  } = props;

  const transition = () => (
    <TransitionSeries.Transition
      presentation={fade()}
      timing={linearTiming({ durationInFrames: transitionDurationInFrames })}
    />
  );

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
            <Clip clip={clip} grade={grade} />
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
          startFrom={Math.round(audioFirstBeatOffset * 30)}
          volume={0.85}
        />
      ) : null}
    </AbsoluteFill>
  );
};
