# Contribuer

## Environnement

Suivre les commandes d'installation du [README](README.md), puis travailler
dans l'environnement `.venv`. Les dépendances de développement sont déclarées
dans `pyproject.toml` ; aucune dépendance applicative n'est encore choisie.

## Code et tests

- Écrire le code, les identifiants, les commentaires, les docstrings et les tests
  en anglais.
- Placer le package dans `src/blackboard_downloader/` et les tests dans `tests/`.
- Garder les modules lisibles et réutiliser les bibliothèques et utilitaires
  existants lorsque c'est pertinent.
- Ajouter ou adapter les tests pour chaque changement de comportement.
- Exécuter `python -m ruff check .`, `python -m ruff format --check .` et
  `python -m pytest` avant de committer. Durant l'initialisation, l'absence de
  code et de tests est attendue ; pytest retourne alors le code 5.
- Garder la documentation cohérente avec les fonctionnalités disponibles.
- Ne pas versionner les identifiants Blackboard, cookies, jetons ou fichiers
  téléchargés. Utiliser `downloads/` pour les téléchargements locaux.

## Git

- Créer une branche dédiée à chaque changement.
- Utiliser des [Conventional Commits](https://www.conventionalcommits.org/),
  par exemple `chore: initialize project` ou `feat: download course files`.
- Garder les commits ciblés et faciles à relire.
- Donner aux pull requests un titre clair et une description brève du besoin,
  des changements et des vérifications effectuées.
- Les agents doivent committer leur travail terminé localement sans pousser.

Les consignes complètes du dépôt sont dans [AGENTS.md](AGENTS.md).
