# OSINTBox — Plan (nom provisoire)

Statut (2026-08-25) : **Roadmap initiale (Phases 0 à 5) complète, plus une interface desktop,
theHarvester et un packaging exe+installeur** — voir [README.md](README.md) pour l'état
d'implémentation à jour (catalogue/normalisation/runner/validateurs/consentement/queue, 4
outils intégrés : Sherlock + Maigret + Holehe + theHarvester, schéma commun validé sur des
formats de sortie différents, file d'attente avec profil de délai + backoff sur rate-limit
validée en conditions réelles, restitution en streaming par outil + récapitulatif final par
catégorie, module de dorking via l'API officielle Google Custom Search — actuellement bloqué,
voir ci-dessous —, export final consolidé JSON+CSV, interface desktop PySide6 en MVP —
`osintbox_app.py`, build exe+installeur — `build_exe.bat`/`installer.iss`). Le reste de ce
document (architecture cible) reste la référence pour d'éventuelles extensions futures
(amass/subfinder, section 3 — binaires Go, le premier vrai cas de dépendance non-Python à
résoudre ; gaps notés en mémoire : cache de résultats entre runs, dépôt git).

**Packaging exe+installeur (2026-08-25)** : même pipeline que scan_system (PyInstaller
`--onefile --windowed` + Inno Setup), avec une différence structurelle importante — OSINTBox
**orchestre** 4 outils externes en sous-processus (contrairement à scan_system, autonome).
Décidé avec l'utilisateur : l'installeur ne les embarque pas, juste un rappel affiché en fin
d'installation qu'ils doivent être pip-installés et accessibles sur le PATH séparément (voir
README.md). Vrai bug trouvé et corrigé avant le build : `store.py`/`runner.py`/`config.py`
résolvaient tous leurs chemins via `Path(__file__).resolve().parent.parent`, ce qui pointe
vers `sys._MEIPASS` (dossier temporaire, nettoyé à la fermeture) une fois figé en exe —
résultats de recherches et clé API auraient été perdus à chaque fermeture. Corrigé par
`osintbox/paths.py::user_data_dir()` (racine du projet en script, `%LOCALAPPDATA%\OSINTBox`
en exe figé), validé par un vrai build+lancement (le dossier `%LOCALAPPDATA%\OSINTBox` a été
créé par l'exe réel, pas juste en test unitaire). `choco install innosetup` a échoué
(`UnauthorizedAccessException`, non-élévation), mais Inno Setup 7 était en fait déjà installé
(`C:\Program Files\Inno Setup 7\ISCC.exe`) — je n'avais vérifié que l'ancien chemin v6/x86,
erreur signalée par l'utilisateur. `installer.iss` compile sans souci (compiler un script ne
demande pas d'élévation, contrairement à installer un paquet via choco) :
`installer_output\OSINTBoxSetup.exe` produit (52,7 Mo). Pas encore installé pour de vrai
(`PrivilegesRequired=admin`, UAC non automatisable depuis cette session). 110 tests au total.

**theHarvester — friction réelle rencontrée (2026-08-25)** : pas publiable proprement sur PyPI
(le nom `theharvester` y est un package squatté vide, v0.0.1) — installé depuis GitHub
(`git+https://github.com/laramies/theHarvester.git`). Le HEAD actuel (5.0.0) exige
Python ≥ 3.14, incompatible avec le Python 3.12 du reste du projet — épinglé au dernier tag
compatible (`4.11.1`). Source de données par défaut : `crtsh` (logs de transparence des
certificats), la seule source gratuite sans clé API parmi celles proposées (la plupart
exigent shodan/censys/hunter/securitytrails...). Limite acceptée : crt.sh est un service
communautaire gratuit notoirement instable (confirmé en direct pendant l'intégration : un
`HTTP 502` observé via `curl` sur crt.sh, theHarvester renvoyant alors silencieusement "0
hôtes trouvés" sans surfacer d'erreur) — invisible à `runner.looks_rate_limited()`, aucune
trace exploitable dans stdout/stderr. Pas un bug côté OSINTBox : validé par un premier run
propre (46 sous-domaines réels sur `python.org`) avant que crt.sh ne tombe.

**Dorking (Phase 4) — bloqué par un changement externe de Google (2026-08-25)** : le code
(`dorking.py`/`search_providers.py`/`config.py`) est fonctionnel et testé, mais Google a
retiré "Rechercher sur l'ensemble du Web" pour tout **nouveau** moteur Custom Search depuis le
2026-01-20 (confirmé en direct : bascule grisée en créant un moteur, message "Cette
fonctionnalité va être obsolète et ne peut plus être activée"). Un moteur créé aujourd'hui est
restreint aux sites explicitement listés (50 max) — inutilisable pour du dorking où la cible
change à chaque run. Alternative gratuite envisagée (Brave Search API) également fermée aux
nouveaux comptes sans carte bancaire depuis début 2026 (recherché en direct, sources dans
[README.md](README.md)). **Décision avec l'utilisateur : laisser bloqué pour l'instant**,
même statut que le breach-checking HIBP (bloqué par un coût/une restriction externe, à
revisiter si l'utilisateur veut payer ou si un fournisseur rouvre un accès gratuit) — pas de
retrait du code, juste un statut "bloqué" documenté.

**Révision du point ouvert "CLI seule vs UI web" (section 7) — 2026-08-25** : la décision
initiale "CLI d'abord, UI web ensuite si besoin confirmé" n'avait pas mis sur la table
l'option desktop native (le choix proposé était CLI vs *web*). L'utilisateur voulait en
réalité une interface desktop, dans l'esprit de PenBox (PySide6/Qt, pas un navigateur) — le
mockup web (`OSINT-Box.jpg`, `maquette_design.png`) était une référence de direction visuelle,
pas littéralement "il faut du web". Tranché : interface desktop PySide6 en MVP (voir
README.md), pas de parité complète avec PenBox (pas d'historique de runs, pas de dialogue de
diff — hors de propos pour un outil OSINT local sans exécution distante).

## 1. Objectif

Créer un outil d'agrégation OSINT similaire dans l'esprit à **penbox** : une boîte à outils qui orchestre plusieurs outils de recon existants (dorking, sherlock, maigret, etc.), normalise leurs résultats, et les présente par catégorie avec une prévisualisation en temps réel plutôt que d'attendre la fin de chaque scan.

Usage visé : recon OSINT dans un cadre autorisé (pentest, bug bounty, red team, recherche perso sur sa propre surface d'exposition).

## 2. Architecture cible

### 2.1 Orchestrateur central
- Core qui invoque chaque outil comme un **module/plugin**, jamais en dur.
- Interface commune par module :
  - `name` : identifiant de l'outil
  - `category` : catégorie(s) de recon couverte(s)
  - `run(target, options) -> raw_output`
  - `rate_limit_profile` : délai/backoff propre à l'outil
- Permet d'ajouter/retirer un outil sans toucher au core.

### 2.2 Couche de normalisation
- Chaque outil a un format de sortie différent (JSON, texte brut, CSV, stdout libre...).
- Un parser par module convertit vers un schéma commun, par ex. :
  ```json
  {
    "source": "sherlock",
    "category": "username",
    "type": "social_profile",
    "value": "https://...",
    "confidence": "high",
    "raw": { ... }
  }
  ```
- C'est cette couche qui alimente la preview — sans elle, les résultats sont incohérents entre outils.

### 2.3 Catégorisation
Regrouper par **type de recon**, pas par outil (un outil peut apparaître dans plusieurs catégories) :
- `username` (sherlock, maigret)
- `email` (holehe, breach-checkers)
- `domaine / DNS` (theHarvester, amass, subfinder)
- `dorking` (Google/Bing dorks custom)
- `réseaux sociaux` (maigret, socialscan)
- `breach / leak` (dehashed-like, HIBP si clé API dispo)
- `image / metadata` (exiftool, reverse image plus tard)

### 2.4 Queue + throttling
- File d'attente par target, exécution séquentielle ou par petits lots (pas de tout-parallèle).
- Profil de délai par outil : sherlock/maigret font du bruteforce sur des centaines de sites, le dorking dépend du moteur de recherche → risques de rate-limit / ban IP différents selon l'outil.
- Backoff automatique si un module se fait rate-limiter, avec statut visible (`running` / `done` / `failed` / `rate-limited`).

### 2.5 Preview / restitution
- Résultats affichés **au fur et à mesure** (streaming par module terminé), pas attendre la fin du scan complet.
- État par module visible dans l'UI.
- Export final consolidé (JSON/CSV/rapport) une fois les modules terminés.

## 3. Outils envisagés (point de départ, à valider)

| Outil | Catégorie | Type d'intégration |
|---|---|---|
| Sherlock | username | subprocess CLI |
| Maigret | username / réseaux sociaux | subprocess CLI |
| theHarvester | domaine / email | subprocess CLI |
| holehe | email | subprocess CLI |
| Dorking custom | dorking | requêtes moteur de recherche (scraping ou API) |
| amass / subfinder | domaine / DNS | subprocess CLI (à évaluer plus tard) |

## 4. Stack technique (proposition, à discuter)

- Backend : Python (cohérent avec la plupart des outils OSINT existants, faciles à wrapper).
- Orchestration : queue simple (ex. asyncio + semaphore par catégorie, ou RQ/Celery si besoin de robustesse plus tard).
- Frontend : à définir — CLI d'abord (plus rapide à livrer), UI web ensuite si le besoin de preview visuelle se confirme.
- Stockage résultats : fichiers JSON par run dans un premier temps, DB (SQLite) si besoin d'historique/comparaison entre scans.

## 5. Roadmap (esquisse)

1. **Phase 0 — socle** : interface module commune + 1 seul outil intégré (ex. sherlock) bout en bout, CLI only.
2. **Phase 1 — normalisation** : ajouter maigret, valider le schéma commun de sortie sur 2 outils différents.
3. **Phase 2 — queue/throttling** : gérer le rate-limit proprement, statuts par module.
4. **Phase 3 — catégorisation + preview** : regrouper par catégorie, affichage streaming (CLI riche ou web).
5. **Phase 4 — dorking** : intégrer le module de dorking (le plus sensible côté rate-limit/ToS).
6. **Phase 5 — extensions** : email/breach, export rapport, autres outils.

## 6. Points d'attention

- **Rate-limit / ban IP** : sherlock/maigret + dorking sont les plus à risque, à throttler dès la phase 2.
- **ToS des plateformes ciblées** : usage strictement dans un cadre autorisé (pentest/bug bounty avec périmètre validé, ou recherche sur sa propre identité).
- **Pas de scraping agressif par défaut** : profils de délai conservateurs, ajustables.

## 7. Points ouverts (à trancher plus tard)

- Nom définitif (OSINTBox = provisoire).
- CLI seule vs UI web dès le départ.
- Faut-il un vrai système de plugins dynamique (découverte auto) ou une liste statique de modules pour commencer plus simple.
- Lien éventuel avec penbox (réutiliser une partie de son architecture/code, ou repartir de zéro).
