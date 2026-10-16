import os
import sys

# Garante que a raiz do projeto esteja no caminho de busca do Python,
# para que "import tools", "import agent", "import banco" funcionem
# ao rodar o pytest de qualquer lugar.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
