# Blackboard Downloader

Projet Python destiné à télécharger les fichiers et dossiers de tout ou partie
des cours Blackboard, en conservant leur arborescence.

**État actuel :** initialisation du projet uniquement. Aucun téléchargement,
module Python ou point d'entrée n'est encore implémenté.

## Installation

Prérequis : Python 3.11 ou supérieur et Git.
Depuis la racine du dépôt, sous Windows (PowerShell) :

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Sous Linux ou macOS :

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Le dossier `.venv/` reste local et n'est pas versionné.
Sous PowerShell, si l'activation est bloquée, utiliser directement
`.\.venv\Scripts\python.exe` à la place de `python` sans modifier la politique
d'exécution du système.

## Utilisation

La future application permettra de sélectionner les cours et contenus à
télécharger, puis de les enregistrer en conservant leur organisation.
La commande de lancement et la configuration de Blackboard seront documentées
lors de leur implémentation.

## Développement et tests

```sh
python -m ruff check .
python -m ruff format --check .
python -m pytest
python -m build
```

Ruff assure le lint et le formatage ; pytest exécutera les tests placés dans
`tests/`. Tant qu'aucun test n'existe, pytest signale « no tests ran » et retourne
le code 5. Aucun test artificiel n'est ajouté à cette initialisation.

Les règles de contribution figurent dans [CONTRIBUTING.md](CONTRIBUTING.md).

## Structure

```text
blackboard-downloader/
├── src/blackboard_downloader/  # Futur package Python
├── tests/                    # Futurs tests automatisés
├── AGENTS.md                 # Consignes du dépôt
├── CONTRIBUTING.md           # Guide de contribution
├── LICENSE                   # Texte intégral de la GPLv3
├── README.md
└── pyproject.toml            # Métadonnées, dépendances et outils
```

## Licence

Projet sous GNU General Public License version 3 uniquement (`GPL-3.0-only`).
Voir [LICENSE](LICENSE) pour le texte intégral.
