# Publicador da @gta6desk

Publica no Instagram, pela **API oficial**, o que está em `fila.json` para cada dia. Corre sozinho no GitHub Actions às **13:00 de Lisboa**. Não precisa do Mac ligado.

- `fila.json`: o que sai e quando (data, hora de Lisboa, ficheiro).
- `stories/`: as imagens (JPEG 1080x1920). O repositório é público porque a API só aceita imagens num link público.
- `registo.csv`: uma linha por publicação (escrita pelo próprio publicador).
- `publicar.py`: o programa. `tests/`: os testes, que correm antes de cada publicação. Se um falhar, não se publica nada.

**Chave:** fica só em *Settings → Secrets and variables → Actions*, como `IG_TOKEN` (e `IG_USER_ID`, opcional). Nunca em ficheiros.

**Testar sem publicar:** *Actions → publicar → Run workflow* com "Só simular" ligado.

**Se falhar:** o GitHub manda email ao dono do repositório. A story desse dia publica-se à mão. O publicador não recupera dias passados.
