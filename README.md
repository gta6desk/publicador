# Publicador da @gta6desk

Publica no Instagram, pela **API oficial**, o que está em `fila.json` para cada dia. Quem o dispara a horas é o **cron-job.org** (13:07 e 13:22 stories; 19:07 e 19:22 posts, hora de Lisboa); os agendamentos do GitHub ficam de reserva, e a vigia (13:47 e 19:47) manda email se nada saiu. Não precisa do Mac ligado.

**Agendador (desde 28/10):** antes de publicar, `agendar.py` lê o repositório `mesa` (só leitura, segredo `MESA_TOKEN`) e acerta a fila: um post entra quando o Ibiki o passou e um sócio o aprovou em `vereditos.md` depois da última mudança; sai se deixar de estar assim. Vai para o primeiro dia livre a partir de amanhã, às 19:00. No máximo 8 mudanças por corrida. Se o molde, os fundos ou a marca da mesa mudarem, refaz os slides dos posts que ainda vão sair (mesma data). Posts já desenhados (ex.: os do Rodri) levam "pronto" no post.json e não passam pelo molde; "sem_ibiki" quando os sócios decidiram que não passam pelo Ibiki. Se o agendador falhar, publica-se o que já estava na fila e o GitHub manda email.

- `fila.json`: o que sai e quando (data, hora de Lisboa, ficheiro).
- `stories/`: as stories (JPEG 1080x1920). `posts/`: os carrosséis (JPEG 1080x1350, legenda na fila). O repositório é público porque a API só aceita imagens num link público.
- `registo.csv`: uma linha por publicação (escrita pelo próprio publicador).
- `publicar.py`: o programa. `tests/`: os testes, que correm antes de cada publicação. Se um falhar, não se publica nada.

**Chave:** fica só em *Settings → Secrets and variables → Actions*, como `IG_TOKEN` (e `IG_USER_ID`, opcional). Nunca em ficheiros.

**Testar sem publicar:** *Actions → publicar → Run workflow* com "Só simular" ligado.

**Se falhar:** o GitHub manda email ao dono do repositório. A story desse dia publica-se à mão. O publicador não recupera dias passados.
