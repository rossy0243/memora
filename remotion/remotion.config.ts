import { Config } from "@remotion/cli/config";

// H.264, qualite elevee : ces films sont le livrable premium.
Config.setVideoImageFormat("jpeg");
Config.setCodec("h264");
Config.setCrf(18);
Config.setChromiumOpenGlRenderer("angle");
// Rendu deterministe : meme entree, meme sortie.
Config.setConcurrency(null);
