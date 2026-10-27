# Publicador da @gta6desk

Publica no Instagram, pela **API oficial**, o que está em `fila.json` para cada dia. Corre sozinho no GitHub Actions às **13:07 de Lisboa** (2.ª tentativa às 13:22; vigia às 13:47 manda email se nada saiu). Não precisa do Mac ligado.

- `fila.json`: o que sai e quando (data, hora de Lisboa, ficheiro).
- `stories/`: as stories (JPEG 1080x1920). `posts/`: os carrosséis (JPEG 1080x1350, legenda na fila). O repositório é público porque a API só aceita imagens num link público.
- `registo.csv`: uma linha por publicação (escrita pelo próprio publicador).
- `publicar.py`: o programa. `tests/`: os testes, que correm antes de cada publicação. Se um falhar, não se publica nada.

**Chave:** fica só em *Settings → Secrets and variables → Actions*, como `IG_TOKEN` (e `IG_USER_ID`, opcional). Nunca em ficheiros.

**Testar sem publicar:** *Actions → publicar → Run workflow* com "Só simular" ligado.

**Se falhar:** o GitHub manda email ao dono do repositório. A story desse dia publica-se à mão. O publicador não recupera dias passados.
