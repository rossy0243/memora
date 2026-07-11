# Bibliotheque musicale locale Memora

Les pistes embarquees par Memora sont placees dans `assets/music/`.
Ce dossier est versionne par Git et inclus dans l'image Docker, afin que la bibliotheque musicale soit disponible aussi en production.

Toutes les pistes ci-dessous proviennent d'OpenGameArt et sont indiquees comme `CC0` sur leurs pages sources.

## Pistes ajoutees

| Mood Memora | Fichier local | Source | Auteur | Licence |
| --- | --- | --- | --- | --- |
| `romantic_cinematic` | `romantic_cinematic_synthwave_421k.mp3` | https://opengameart.org/content/calm-relax-1-synthwave-421k | The Cynic Project / cynicmusic | CC0 |
| `cinematic_emotional` | `cinematic_emotional_emotional_piano_loop.mp3` | https://opengameart.org/content/emotional-piano-loop | extenz | CC0 |
| `joyful_party` | `joyful_party_party_sector.mp3` | https://opengameart.org/content/party-sector | Joth | CC0 |
| `warm_lounge` | `warm_lounge_one_step_at_a_time.mp3` | https://opengameart.org/content/one-step-at-a-time | Pro Sensory / Alex McCulloch | CC0 |
| `elegant_warm` | `elegant_warm_a_new_town.mp3` | https://opengameart.org/content/a-new-town-rpg-theme | The Cynic Project / cynicmusic | CC0 |

## Notes produit

- Ces pistes sont suffisantes pour tester le choix automatique de musique et le ducking voix/musique en local comme en production.
- Avant une mise en production SaaS, refaire une passe juridique et remplacer si besoin par une bibliotheque achetee ou un catalogue avec contrat explicite.
- Garder les noms de fichiers avec les tokens de mood (`romantic`, `cinematic`, `joyful`, etc.) : le selecteur de Memora s'en sert pour choisir une piste automatiquement.
