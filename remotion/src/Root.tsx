import React from "react";
import { Composition } from "remotion";
import { MemoraFilm } from "./MemoraFilm";
import { defaultFilmProps, FilmProps } from "./types";
import { totalDurationInFrames } from "./timeline";

const FPS = 30;

// Un exemple par defaut pour le Studio (aperçu sans Django).
const sampleClips: FilmProps["clips"] = [
  { kind: "image", src: "sample/1.jpg", durationInFrames: 90 },
  { kind: "image", src: "sample/2.jpg", durationInFrames: 90 },
  { kind: "image", src: "sample/3.jpg", durationInFrames: 90 },
];

export const RemotionRoot: React.FC = () => {
  return (
    <>
      {/* Teaser vertical 9:16 — le format partage. */}
      <Composition
        id="Teaser"
        component={MemoraFilm}
        fps={FPS}
        width={1080}
        height={1920}
        defaultProps={{ ...defaultFilmProps, clips: sampleClips }}
        calculateMetadata={({ props }) => ({
          durationInFrames: totalDurationInFrames(props),
        })}
      />
      {/* Film heros 16:9. */}
      <Composition
        id="Hero"
        component={MemoraFilm}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{ ...defaultFilmProps, clips: sampleClips }}
        calculateMetadata={({ props }) => ({
          durationInFrames: totalDurationInFrames(props),
        })}
      />
      {/* Integrale 16:9 (meme composition, plus de clips). */}
      <Composition
        id="Full"
        component={MemoraFilm}
        fps={FPS}
        width={1920}
        height={1080}
        defaultProps={{ ...defaultFilmProps, clips: sampleClips }}
        calculateMetadata={({ props }) => ({
          durationInFrames: totalDurationInFrames(props),
        })}
      />
    </>
  );
};
