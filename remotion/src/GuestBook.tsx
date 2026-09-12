import React from "react";
import {
  AbsoluteFill,
  Audio,
  OffthreadVideo,
  interpolate,
  staticFile,
  useVideoConfig,
} from "remotion";
import { TransitionSeries, linearTiming } from "@remotion/transitions";
import { fade } from "@remotion/transitions/fade";
import { GuestBookProps } from "./types";
import { TitleCard } from "./TitleCard";
import { NameCard } from "./NameCard";
import { gradeFilter, splitToneOverlay, vignette } from "./grade";
import { FilmGrain } from "./FilmGrain";

function resolveSrc(src: string): string {
  return /^https?:\/\//.test(src) ? src : staticFile(src);
}

// Un message du livre d'or : la video en entier, cadree contain sur un fond
// floute (pas de bandes noires), grade chaud, vignette. Pas de Ken Burns —
// ce sont des gens qui parlent face camera, un zoom lent les rendrait bancals.
// Le son du message est toujours garde, avec une courte rampe d'entree/sortie
// (~200 ms) pour que la voix ne saute pas d'un plan a l'autre.
const GuestBookClip: React.FC<{
  src: string;
  durationInFrames: number;
  grade: GuestBookProps["grade"];
  transitionDurationInFrames: number;
}> = ({ src, durationInFrames, grade, transitionDurationInFrames }) => {
  const resolved = resolveSrc(src);

  // Rampe alignee sur la transition visuelle (voir Clip.tsx : meme raisonnement).
  const fadeFrames = Math.max(
    1,
    Math.min(transitionDurationInFrames, Math.floor(durationInFrames / 2))
  );
  const voiceVolumeAt = (localFrame: number): number =>
    interpolate(
      localFrame,
      [0, fadeFrames, durationInFrames - fadeFrames, durationInFrames],
      [0, 1, 1, 0],
      { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
    );

  return (
    <AbsoluteFill style={{ backgroundColor: "#0f0c0d", overflow: "hidden" }}>
      <AbsoluteFill
        style={{ transform: "scale(1.2)", filter: "blur(40px) brightness(0.5)" }}
      >
        <AbsoluteFill
          style={{ display: "flex", justifyContent: "center", alignItems: "center" }}
        >
          <div style={{ width: "100%", height: "100%" }}>
            <OffthreadVideo
              src={resolved}
              muted
              style={{ width: "100%", height: "100%", objectFit: "cover" }}
            />
          </div>
        </AbsoluteFill>
      </AbsoluteFill>

      <AbsoluteFill
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          filter: gradeFilter(grade),
        }}
      >
        <OffthreadVideo
          src={resolved}
          volume={voiceVolumeAt}
          style={{ width: "100%", height: "100%", objectFit: "contain" }}
        />
      </AbsoluteFill>

      <AbsoluteFill style={{ background: splitToneOverlay(grade), mixBlendMode: "soft-light" }} />
      <AbsoluteFill style={{ background: vignette }} />
    </AbsoluteFill>
  );
};

// Montage integral du livre d'or : carton d'ouverture -> [carton « De la part
// de … » -> message] pour chaque invite -> carton de fin. Fondus enchaines
// partout. Musique : un lit tres discret, encore baisse pendant chaque message.
export const GuestBookMontage: React.FC<GuestBookProps> = (props) => {
  const {
    messages,
    audioSrc,
    audioFirstBeatOffset,
    title,
    subtitle,
    outroTitle,
    introDurationInFrames,
    outroDurationInFrames,
    nameCardDurationInFrames,
    transitionDurationInFrames,
    grade,
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

  // Fenetres [debut, fin] (en frames) de chaque message : la musique y descend
  // a duckedMusicVolume. Dans une TransitionSeries chaque transition chevauche
  // les deux sequences voisines, donc on retranche une transition par jonction.
  const voiceSegments: Array<[number, number]> = [];
  let segStart = introDurationInFrames - transitionDurationInFrames;
  for (const message of messages) {
    segStart += nameCardDurationInFrames - transitionDurationInFrames;
    voiceSegments.push([segStart, segStart + message.durationInFrames]);
    segStart += message.durationInFrames - transitionDurationInFrames;
  }

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

        {messages.flatMap((message, index) => [
          transition(),
          <TransitionSeries.Sequence
            key={`name-${index}`}
            durationInFrames={nameCardDurationInFrames}
          >
            <NameCard
              name={message.guestName}
              durationInFrames={nameCardDurationInFrames}
            />
          </TransitionSeries.Sequence>,
          transition(),
          <TransitionSeries.Sequence
            key={`message-${index}`}
            durationInFrames={message.durationInFrames}
          >
            <GuestBookClip
              src={message.src}
              durationInFrames={message.durationInFrames}
              grade={grade}
              transitionDurationInFrames={transitionDurationInFrames}
            />
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

      <FilmGrain />
    </AbsoluteFill>
  );
};
