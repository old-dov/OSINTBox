"""Interface desktop (PySide6) d'OSINTBox -- MVP, meme framework et meme convention de
lancement que PenBox (voir penbox_app.py) : un point d'entree racine (osintbox_app.py) qui
construit QApplication et affiche MainWindow. Couche fine par-dessus le backend CLI existant
(catalog/queue/normalizers/store) -- aucune logique metier dupliquee ici."""
