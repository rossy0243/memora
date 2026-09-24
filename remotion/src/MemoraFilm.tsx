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
import { MessageCard, StatsCard } from "./InterludeCards";
import { HighlightCollage } from "./HighlightCollage";
import { FilmGrain } from "./FilmGrain";
import { Watermark } from "./Watermark";
import { coldOpenIndex as resolveColdOpenIndex, mainClips as resolveMainClips } from "./timeline";

function resolveSrc(src: string): string {
  return /^https?:\/\//.test(src) ? src : staticFile(src);
}

// Bandeaux "scope" (2.35:1) : reserves au heros, jamais au teaser (vertical,
// deja plein cadre) ni a l'integrale (format de conservation, pas de spectacle).
const CINEMATIC_ASPECT_RATIO = 2.35;

interface Segment {
  key: string;
  duration: number;
  node: React.ReactNode;
  // Voix des invites a suivre pour le ducking musical (uniquement les plans).
  keepAudio?: boolean;
}

// Le film complet : carton d'ouverture -> [mot des maries] -> plans en fondus
// enchaines -> [mini-collage] -> [recap en chiffres] -> carton de fin, avec une
// piste musicale par-dessus. Construit comme une liste de segments plutot qu'un
// JSX fige : chaque carton additionnel (Django, voir processing.remotion) est
// optionnel et simplement absent de la liste quand son contenu est vide — la
// meme regle de presence doit etre appliquee cote timeline.ts (duree totale
// annoncee a Remotion), sinon la composition dure plus/moins longtemps que ce
// qu'elle rend reellement.
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
    cinematicBars,
    watermark,
    coldOpenClipIndex,
    welcomeMessage,
    welcomeMessageDurationInFrames,
    stats,
    statsDurationInFrames,
    highlightClips,
    highlightDurationInFrames,
  } = props;
  const { fps, width, height } = useVideoConfig();

  // Ouverture a froid : les 2,5 premieres secondes montrent le plan choisi
  // (le mieux note cote Python, pas forcement le premier chronologique) seul
  // et muet, puis le titre se pose dessus en fondu — jamais un carton plein
  // qui demarre sec. On borne pour garder un minimum de texte lisible meme sur
  // un intro tres court. Ce plan ne reapparait pas juste apres dans le montage
  // (mainClips, partage avec timeline.ts pour que la duree annoncee de la
  // composition corresponde exactement a ce qui est rendu ici).
  const resolvedColdOpenIndex = resolveColdOpenIndex(clips, coldOpenClipIndex);
  const coldOpenFrames = resolvedColdOpenIndex >= 0
    ? Math.min(Math.round(fps * 2.5), Math.max(introDurationInFrames - Math.round(fps * 1.5), 0))
    : 0;
  const coldOpenBackground = resolvedColdOpenIndex >= 0
    ? { ...clips[resolvedColdOpenIndex], keepAudio: false, durationInFrames: introDurationInFrames }
    : null;
  const mainClipList = resolveMainClips(clips, coldOpenClipIndex);

  // Bandeaux "scope" : hauteur calculee pour amener le cadre 16:9 a 2.35:1,
  // sans jamais recadrer le contenu — juste deux bandes posees par-dessus.
  const barHeight = cinematicBars
    ? Math.max((height - width / CINEMATIC_ASPECT_RATIO) / 2, 0)
    : 0;

  const transition = (key: string) => (
    <TransitionSeries.Transition
      key={key}
      presentation={fade()}
      timing={linearTiming({ durationInFrames: transitionDurationInFrames })}
    />
  );

  // Le lower-third (nom du moment) ne s'affiche que sur le PREMIER plan de chaque
  // moment : il marque l'entree dans un nouveau chapitre (Cérémonie, Soirée…)
  // sans repeter le libelle sur chaque photo.
  const seenLabels = new Set<string>();
  const clipLabels = mainClipList.map((clip) => {
    const label = clip.label?.trim();
    if (!label || seenLabels.has(label)) return undefined;
    seenLabels.add(label);
    return label;
  });

  const showHighlight = Boolean(highlightClips && highlightClips.length >= 2);
  const showWelcome = Boolean(welcomeMessage);
  const showStats = Boolean(stats);

  const introNode = coldOpenBackground ? (
    <AbsoluteFill>
      <Clip clip={coldOpenBackground} grade={grade} pace="gentle" />
      <TitleCard
        title={title}
        subtitle={subtitle}
        durationInFrames={introDurationInFrames}
        transparentBg
        revealDelay={coldOpenFrames}
      />
    </AbsoluteFill>
  ) : (
    <TitleCard title={title} subtitle={subtitle} durationInFrames={introDurationInFrames} />
  );

  const segments: Segment[] = [{ key: "intro", duration: introDurationInFrames, node: introNode }];

  if (showWelcome) {
    segments.push({
      key: "welcome",
      duration: welcomeMessageDurationInFrames ?? 0,
      node: (
        <MessageCard
          message={welcomeMessage as string}
          signature={title}
          durationInFrames={welcomeMessageDurationInFrames ?? 0}
        />
      ),
    });
  }

  mainClipList.forEach((clip, index) => {
    segments.push({
      key: `clip-${index}`,
      duration: clip.durationInFrames,
      keepAudio: clip.keepAudio,
      node: (
        <Clip
          clip={clip}
          grade={grade}
          pace={pace}
          chapterLabel={clipLabels[index]}
          transitionDurationInFrames={transitionDurationInFrames}
        />
      ),
    });
  });

  if (showHighlight) {
    segments.push({
      key: "highlight",
      duration: highlightDurationInFrames ?? 0,
      node: (
        <HighlightCollage
          clips={highlightClips!}
          grade={grade}
          durationInFrames={highlightDurationInFrames ?? 0}
        />
      ),
    });
  }

  if (showStats && stats) {
    segments.push({
      key: "stats",
      duration: statsDurationInFrames ?? 0,
      node: (
        <StatsCard
          totalMemories={stats.totalMemories}
          contributors={stats.contributors}
          durationInFrames={statsDurationInFrames ?? 0}
        />
      ),
    });
  }

  segments.push({
    key: "outro",
    duration: outroDurationInFrames,
    node: (
      <TitleCard
        title={outroTitle}
        subtitle={title}
        durationInFrames={outroDurationInFrames}
        showSeal
      />
    ),
  });

  // Segments [debut, fin] (en frames) des plans qui gardent la voix des invites.
  // Dans une TransitionSeries, chaque transition CHEVAUCHE les deux sequences :
  // un segment commence donc a (somme des durees precedentes) - (n+1) transitions.
  const voiceSegments: Array<[number, number]> = [];
  let segmentStart = 0;
  segments.forEach((segment, index) => {
    if (index > 0) segmentStart -= transitionDurationInFrames;
    if (segment.keepAudio) {
      voiceSegments.push([segmentStart, segmentStart + segment.duration]);
    }
    segmentStart += segment.duration;
  });

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
        {segments
          .flatMap((segment, index) => [
            index > 0 ? transition(`transition-${index}`) : null,
            <TransitionSeries.Sequence key={segment.key} durationInFrames={segment.duration}>
              {segment.node}
            </TransitionSeries.Sequence>,
          ])
          .filter((node): node is React.ReactElement => node !== null)}
      </TransitionSeries>

      {audioSrc ? (
        <Audio
          src={resolveSrc(audioSrc)}
          startFrom={Math.round(audioFirstBeatOffset * fps)}
          volume={musicVolumeAt}
        />
      ) : null}

      <FilmGrain />

      {watermark ? <Watermark topInset={cinematicBars ? barHeight : 0} /> : null}

      {cinematicBars && barHeight > 0 ? (
        <>
          <AbsoluteFill style={{ top: 0, height: barHeight, background: "#000" }} />
          <AbsoluteFill style={{ top: "auto", bottom: 0, height: barHeight, background: "#000" }} />
        </>
      ) : null}
    </AbsoluteFill>
  );
};
