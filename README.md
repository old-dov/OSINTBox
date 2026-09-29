# OSINTBox

Orchestrateur d'outils de recon OSINT (dans l'esprit de [PenBox](../%28Block%20Rocking%20Bytes%29/B2DR/%5BScripts%20%28cybersec%29%5D/penbox_plan.md)) :
wrapper plusieurs outils existants (Sherlock, Maigret, Holehe, theHarvester...) et l'API Google
Custom Search pour le dorking, normaliser les resultats vers un schema commun, et les
restituer par categorie. Voir [PLAN.md](PLAN.md) pour l'architecture cible complete et la
roadmap.

**Statut : Phase 0 + 1 + 2 + 3 + 4 + 5, plus interface desktop, theHarvester et packaging
exe+installeur (hors roadmap initiale).** Quatre outils integres bout en bout (Sherlock, Maigret, Holehe, theHarvester),
schema commun valide sur des formats de sortie tres differents (stdout texte, vrai JSON
structure). File d'attente sequentielle avec profil de delai par outil et backoff/retry sur
rate-limit, statuts visibles (queued/running/retrying/done/failed/rate-limited/...). Chaque
outil affiche et sauvegarde son resultat des qu'il termine (pas d'attente de la fin de toute
la file, findings partiels conserves meme sur un statut final non-"done"), plus un
recapitulatif final regroupe par categorie de recon (`username`, `email`, `domain`, `dorking`,
etc.), pas par outil. Module de dorking (`--dork`) via l'API officielle Google Custom Search (jamais de scraping
direct des pages de resultats — decide explicitement avec l'utilisateur, voir plan section 6)
-- **code fonctionnel mais actuellement bloque** par un changement externe de Google, voir la
section Configuration plus bas. Export final consolide (JSON + CSV) de tous les findings d'un
run, en
plus des fichiers par outil. **Interface desktop (PySide6)** ajoutee en plus de la CLI, meme
framework et meme convention de lancement que PenBox — MVP (pas de parite complete avec
PenBox : pas d'historique de runs ni de diff, hors de propos pour un outil OSINT local).

## Usage

### CLI

```
pip install -r requirements.txt
python -m osintbox <username> --tool sherlock
python -m osintbox <username> --tool sherlock --tool maigret   # --tool repetable
python -m osintbox <domaine> --tool theharvester                # cible = domaine, pas pseudo
python -m osintbox <domaine> --dork                             # dorking (voir Configuration)
python -m osintbox <username> --yes                             # saute la confirmation
```

theHarvester n'est pas publiable proprement sur PyPI (nom squatte par un package vide) --
`requirements.txt` l'installe depuis GitHub (`git+https://...`), donc `git` doit etre
disponible sur la machine, et l'install est un peu plus lente que pour un paquet PyPI normal.

### Interface desktop

```
pip install -r requirements.txt
python osintbox_app.py
```

Fenetre unique : champ cible, cases a cocher par outil + dorking, bouton Lancer/Arreter,
compteur "temps ecoule (mm:ss) -- X/Y outils termines" mis a jour chaque seconde pendant le
scan, statut des jobs en direct, tableau de resultats (triable par colonne), export JSON+CSV.
L'interface propose un theme clair et un choix Francais/English memorise entre les lancements.
Meme backend que la CLI
(catalog/queue/normalizers/store) — aucune logique dupliquee, juste une couche UI par-dessus,
executee dans un thread separe (`osintbox/ui/worker.py`) pour ne pas geler la fenetre pendant
les delais entre outils / le backoff rate-limit.

Dans l'installation Windows, les outils du catalogue passent par la CLI Rust
`osintbox-rs.exe` placee a cote de `OSINTBox.exe`. Le worker garde les statuts et
les resultats en direct, ainsi que l'arret entre deux outils. Le dorking reste
sur le chemin Python. En lancement depuis les sources, le worker utilise la
queue Python par defaut ; `OSINTBOX_RUST_CLI` peut pointer vers le binaire Rust
pour tester cette integration.

**Arret en cours de scan** : le bouton "Arreter" ne coupe pas un sous-processus deja lance (le
runner fait un `communicate(timeout=...)` bloquant, pas de boucle de polling a interrompre a
mi-course sans reecrire ce mecanisme deja valide) — il empeche seulement le *prochain* outil de
la file de demarrer. L'outil en cours va donc a son terme (borne par son propre timeout).

`--tool` est obligatoire des que plusieurs outils sont enregistres dans le catalogue (sinon
le seul disponible est utilise par defaut). Plusieurs `--tool` passent par la meme file
d'attente (`osintbox/queue.py`), l'un apres l'autre. `--dork` est independant du catalogue
(pas un outil subprocess) et attend un domaine comme cible.

`--yes` saute la confirmation d'autorisation interactive (usage scripte). Sans lui, l'outil
demande une confirmation explicite avant de lancer le scan — a utiliser uniquement dans un
cadre autorise (votre propre identite, ou pentest/bug bounty avec perimetre valide).

Les resultats sont affiches dans le terminal et sauvegardes en JSON dans `results/`
(non versionne — donnees de recon, pas du code).

### Configuration (dorking) -- actuellement bloque, voir note

`--dork` necessite une cle Google Custom Search JSON API :

```
cp osintbox.local.yaml.example osintbox.local.yaml
# puis renseigner google_cse.api_key et google_cse.cx dans osintbox.local.yaml
```

`osintbox.local.yaml` n'est jamais commite (voir `.gitignore`).

**Bloque depuis le 2026-01-20 (changement externe, pas un bug OSINTBox)** : Google a retire
l'option "Rechercher sur l'ensemble du Web" pour tout **nouveau** moteur Custom Search --
confirme en creant un moteur en direct le 2026-08-25 (bascule grisee, "Cette fonctionnalite
va etre obsolete et ne peut plus etre activee"). Un moteur cree APRES le 2026-01-20 est
restreint aux sites explicitement listes (50 max) -- inutilisable pour du dorking generique
ou la cible change a chaque run. Alternative gratuite envisagee (Brave Search API) egalement
fermee aux nouveaux comptes sans carte bancaire depuis debut 2026. Statut : meme categorie que
le breach-checking HIBP -- bloque par un cout/une restriction externe, a revisiter si
l'utilisateur veut payer (Brave Search API : ~5$/mois de credit offert, carte requise) ou si
Google/un autre fournisseur rouvre un acces gratuit.

## Build (exe + installeur)

```
build_exe.bat
```

Produit `dist\OSINTBox.exe` (PyInstaller, `--onefile --windowed`), meme convention que
scan_system, et `dist\osintbox-rs.exe` (Rust, build release). Puis, avec une version stable
d'[Inno Setup](https://jrsoftware.org/isinfo.php) installee (7.1.0 pour le paquet 1.0.3) :

```
"C:\Program Files\Inno Setup 7\ISCC.exe" /DMyAppVersion=1.0.3 installer.iss
```

Produit `installer_output\OSINTBoxSetup-1.0.3.exe` (ou le numero passe via
`/DMyAppVersion`).

**Important** : l'exe packagee n'embarque PAS Sherlock/Maigret/Holehe/theHarvester -- ce sont
des outils tiers invoques en sous-processus. L'installeur copie `requirements-tools.txt`
(dependances des 4 outils, **sans** PySide6 -- deja embarque dans l'exe fige, inutile ici et
indisponible sur un Python 32 bits) a cote de l'exe installe. Pour les installer, **ne pas
creer le venv dans le dossier d'installation** (`Program Files` n'est pas ecrivable sans
elevation -- erreur reelle rencontree en testant) :

```
cd %LOCALAPPDATA%\OSINTBox
python -m venv tools
tools\Scripts\activate
pip install -r "C:\Program Files\OSINTBox\requirements-tools.txt"
```

Ajoutez ensuite `%LOCALAPPDATA%\OSINTBox\tools\Scripts` au PATH systeme, ou lancez toujours
OSINTBox depuis un terminal ou ce venv est active -- sinon `resolve_executable()` ne trouve
pas les outils (voir `osintbox/catalog.py`). L'installeur affiche ce rappel apres
l'installation.

Les donnees utilisateur (resultats, cle API `osintbox.local.yaml`, runs bruts) vont dans
`%LOCALAPPDATA%\OSINTBox\` pour la version installee (Program Files n'est pas ecrivable sans
elevation) -- voir `osintbox/paths.py`. En mode script (`python -m osintbox`/`osintbox_app.py`
depuis les sources), elles restent a la racine du projet comme avant.

## Architecture (Phases 0-5)

- `osintbox/catalog.py` — registre declaratif des outils (`catalog.yaml`), chaque entree
  definit un gabarit de commande (`{target}` substitue au lancement) et un `target_type`.
- `osintbox/validators.py` — validation stricte de la cible selon son type avant tout passage
  en argv (anti-injection).
- `osintbox/runner.py` — execution en sous-processus (timeout + kill), synchrone pour l'instant.
- `osintbox/normalizers.py` — un normaliseur par outil (registre par decorateur) qui convertit
  la sortie brute vers le schema `Finding` commun (`source`/`category`/`type`/`value`/
  `confidence`/`raw`). Deux formats de sortie geres (`output_mode` du catalogue) : stdout texte
  a parser (Sherlock, pas de JSON structure natif) ou vrai fichier JSON (Maigret, `-J simple`).
  Repli generique pour un outil sans normaliseur dedie, quel que soit le format.
- `osintbox/consent.py` — confirmation d'autorisation explicite avant chaque scan.
- `osintbox/queue.py` — file d'attente sequentielle : espace les runs consecutifs d'un meme
  outil (`ToolSpec.min_delay_s`, profil de delai), retente avec backoff croissant si
  `runner.looks_rate_limited()` detecte un blocage, statut visible par job (queued/running/
  retrying/done/failed/timeout/not_found/rate_limited). "retrying" (tentative en cours) est
  distinct de "rate_limited" (abandon final) — chaque statut final n'est emis qu'une fois par
  job, sans ambiguite pour un appelant qui veut extraire des findings ou compter un job une
  seule fois.
- `osintbox/store.py` — sauvegarde JSON par run (`save_run`), plus export consolide JSON+CSV
  de tous les findings d'un run une fois termine (`save_consolidated_report`).
- `osintbox/normalizers.py` (`group_by_category`) — regroupe les findings accumules par
  categorie de recon plutot que par outil source, pour le recapitulatif final.
- `osintbox/cli.py` (`_StreamingReporter`) — point d'entree (`python -m osintbox`) ; affiche et
  sauvegarde le resultat de chaque outil des qu'il atteint un statut terminal dans la queue
  (streaming), puis imprime le recapitulatif categorise une fois tous les jobs termines.
- `osintbox/dorks.py` — gabarits de dorks conservateurs (fichiers exposes, panneaux d'admin,
  fuites git...) pour une cible domaine.
- `osintbox/search_providers.py` — appel a l'API officielle Google Custom Search JSON (jamais
  de scraping direct de page de resultats).
- `osintbox/dorking.py` — orchestration : construit les dorks, les execute avec un delai
  conservateur entre chaque requete, normalise en `Finding`, gere le rate-limit (429) sans
  interrompre les autres normaliseurs d'erreur.
- `osintbox/config.py` — charge les cles API depuis `osintbox.local.yaml` (jamais commite, voir
  `osintbox.local.yaml.example`).
- `osintbox/ui/worker.py` (`ScanWorker`, `QThread`) — execute la queue + le dorking en
  arriere-plan, emet des signaux Qt (statut/findings/erreurs) plutot que de toucher des widgets
  directement depuis ce thread. Cooperatif avec `QThread.requestInterruption()`, verifie par
  `queue.run_queue`/`dorking.run_dorking` (parametre `should_cancel`) entre deux jobs/dorks.
- `osintbox/ui/main_window.py` (`MainWindow`) — fenetre unique : cible, cases a cocher outils/
  dorking, boutons Lancer/Arreter, barre de progression, statut en direct, tableau de
  resultats, export.
- `osintbox_app.py` (racine) — point d'entree desktop (`python osintbox_app.py`), meme
  convention que `penbox_app.py`.
- `osintbox/paths.py` (`user_data_dir`) — resout ou vivent resultats/config/runs bruts :
  racine du projet en script, `%LOCALAPPDATA%\OSINTBox` en exe fige (PyInstaller `--onefile`,
  `sys._MEIPASS` est un dossier temporaire nettoye a la fermeture, inutilisable pour des
  donnees censees survivre).

Adapte de l'architecture [PenBox](../%28Block%20Rocking%20Bytes%29/B2DR/%5BScripts%20%28cybersec%29%5D/penbox/)
(catalogue/normaliseurs/runner/validateurs), generalisee pour wrapper des CLI tierces
(pas forcement Python, pas dans ce depot) plutot que des scripts maison.

## Tests

```
pip install -r requirements-dev.txt
pytest tests/ -v
```
