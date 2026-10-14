# Polaroid Maker

Programa desktop simples que pega uma pasta inteira de fotos e monta cada
uma automaticamente dentro de uma moldura estilo polaroid, no tamanho exato
para importar no software de álbum (ex: Smart Album) ou para impressão
(ex: ímã polaroid).

**Todo projeto é sempre exportado em 300 DPI**, independente do modo — não
tem campo de resolução pra mexer (removido de propósito, pra não ter como
sair um arquivo em resolução mais baixa por engano). No modo máscara PSD,
isso vale pro arquivo final salvo, mesmo que o `.psd` original tenha sido
feito com outro DPI.

Tem três modos:

- **Medidas manuais**: você digita o tamanho da moldura e da janela da foto
  em cm e o programa desenha uma moldura sólida (branca ou de outra cor).
- **Máscara PSD pronta**: você aponta para um arquivo `.psd` que já tem a
  arte da moldura pronta (a mesma que você usa no Photoshop hoje, com uma
  camada de foto/smart object e a arte da moldura por cima). O programa
  encontra sozinho o "buraco" onde a foto entra, encaixa a foto do cliente
  ali e funde tudo exatamente como ficaria no Photoshop — sem precisar
  ajustar cada foto na mão.
- **Grade simples**: pra produtos que são só várias fotos lado a lado numa
  folha, sem nenhuma arte de moldura por trás (ex: BOLA, Imã 15x21 novo).
  Você digita o tamanho da folha, quantas colunas/linhas, o tamanho de cada
  foto e (se tiver) a borda entre elas — o programa monta a grade sozinho.
  Já vem com atalhos pros produtos BOLA e Imã 15x21 novo com os números
  tirados direto do painel "Album Info" do Smart Album.

## Baixar pronto (sem instalar Python)

A pasta [`download/`](download/index.html) tem uma página (`index.html`) com
botão de download do `Polaroid Maker.exe` — um executável único que já leva
tudo junto (Pillow, psd-tools, numpy, scipy), com o ícone do livrinho da
LAB Álbuns embutido nele. Abra `download/index.html` num navegador (local ou
publicado num compartilhamento da rede) pra baixar.

Como o `.exe` não é assinado digitalmente, o Windows SmartScreen avisa "O
Windows protegeu seu PC" na primeira vez — é só clicar em "Mais informações"
→ "Executar assim mesmo".

### Gerar o .exe de novo (depois de alterar o código)

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name "PolaroidMaker" --icon "icon.ico" --add-data "assets;assets" polaroid_maker.py
```

O executável sai em `dist/PolaroidMaker.exe`. Copie pra `download/Polaroid
Maker.exe` (substituindo o antigo) pra atualizar a página de download.

## Instalação (rodando com Python, pra quem for mexer no código)

```bash
python -m pip install -r requirements.txt
```

## Uso

Dê dois cliques em `iniciar.bat`, ou rode:

```bash
python polaroid_maker.py
```

Na janela:

1. **Entrada**: pasta com as fotos originais.
2. **Saída**: pasta onde os polaroids prontos vão ser salvos (mantém as
   originais intactas, cada foto vira `nome_polaroid.jpg`).
3. **Tipo de moldura**: escolha "Medidas manuais", "Máscara PSD pronta" ou
   "Grade simples".

### Modo medidas manuais

4. **Medidas**: já vem preenchido com 12,7×9cm de moldura e 8,77×8,41cm de
   janela da foto. Pode mudar quando precisar para outro projeto — o
   programa recalcula as margens sozinho.
5. **Lado da borda grossa**: escolhe se a "aba" da polaroid fica à esquerda,
   direita, topo ou embaixo (as opções mudam automaticamente dependendo se a
   moldura é mais larga ou mais alta que a foto).
6. **Cor da moldura**: branco por padrão, pode trocar.

### Modo máscara PSD pronta

4. **Arquivo .psd da máscara**: escolha o arquivo, ou clique num dos botões
   de atalho já apontando para as máscaras da pasta `Gabaritos`:
   - **Imã Horizontal** / **Imã Vertical**: uma foto por moldura (ímã avulso).
   - **Folha Imã Horizontal (4x)** / **Folha Imã Vertical (4x)**: a folha de
     impressão de ~15×21cm com 4 ímãs, do jeito que sempre é impressa.

   Depois clique em **Carregar máscara**.
5. O programa lê o PSD, identifica a(s) camada(s) de foto (smart object) e a
   arte da moldura, e calcula sozinho onde é a "janela" de cada foto (a área
   transparente na arte) — funciona tanto pra 1 foto quanto pra várias numa
   folha só, sem precisar configurar nada. Mostra o tamanho final e o
   tamanho da janela em cm pra você conferir, e quantas fotos cabem por
   folha.
6. Se um dia trocarem o design da máscara ou o layout da folha, é só
   carregar o novo `.psd` — não precisa mexer em código nem redigitar
   medida nenhuma.

Quando a máscara tem só 1 janela, cada foto da pasta de entrada vira um
arquivo `nome_polaroid.jpg`. Quando a máscara é uma folha com várias janelas
(ex: 4 imãs), o programa agrupa as fotos da pasta de 4 em 4 (na ordem) e
gera uma folha pronta por grupo (`folha_001.jpg`, `folha_002.jpg`, ...).

Se o **último grupo** sobrar incompleto (ex: sobraram só 2 fotos de um
grupo de 4), o programa remonta a grade automaticamente só com as fotos
que sobraram — **empilhadas** (uma embaixo da outra, cada uma com sua
própria borda), preenchendo a folha toda em vez de deixar metade em
branco. Se não couber empilhado (ex: sobraram 3 fotos), tenta lado a lado;
se nem isso couber, usa a grade original mesmo, com os espaços que
sobrarem em branco.

### Modo grade simples

4. **Atalhos**: clique em **BOLA (6 fotos)** ou **Ima 15x21 novo (4 fotos)**
   pra já preencher os campos com os números certos, ou digite os seus
   próprios:
   - **Folha**: tamanho total da folha de impressão (cm).
   - **Colunas / Linhas**: quantas fotos cabem lado a lado e em pé.
   - **Foto**: tamanho de cada foto individual (cm) — é esse tamanho que
     aparece como "Frame W x H" no Smart Album.
   - **Borda por foto**: uma faixa da cor de borda desenhada por dentro de
     cada foto (0 = sem borda). Não aumenta o tamanho da foto, só corta um
     pouco pra dentro.
   - **Espaço entre fotos**: gap entre uma foto e outra (0 = coladas).
   - **Linha de corte**: uma linha fina (cor e espessura configuráveis) em
     volta de cada foto, pra marcar onde uma termina e a próxima começa —
     o "risco" que serve de guia na hora de cortar (0 = sem linha).
5. O programa centraliza a grade sozinho na folha e avisa se as medidas não
   couberem (aí é só diminuir a foto/borda/espaço ou aumentar a folha).
6. As fotos da pasta são agrupadas de (colunas×linhas) em (colunas×linhas)
   e cada grupo vira uma folha pronta (`folha_001.jpg`, `folha_002.jpg`,
   ...), igual ao modo máscara com várias fotos por folha — incluindo a
   remontagem automática (empilhada) do último grupo quando ele sobra
   incompleto (veja acima).

   Já uma grade **configurada com exatamente 2 fotos no total** (ex:
   Colunas=1, Linhas=2) é diferente: sempre vira **lado a lado** (2x1)
   automaticamente, nunca empilhada — essa regra é só pra quando você
   monta a grade de propósito pra 2 fotos, não pra sobra de lote.

### Em todos os modos

7. **Atualizar prévia e galeria**: atualiza a aba "Prévia" (primeira foto/
   folha) e reconstrói a aba "Todas as fotos".
8. **Processar pasta**: roda em lote todas as fotos da pasta de entrada.

A tela é dividida em abas do lado direito:

- **Prévia**: como fica a primeira foto (ou a primeira folha, no modo com
  várias fotos por folha) já montada na moldura.
- **Todas as fotos**: uma galeria com a prévia de **cada foto** da pasta de
  entrada, já cortada no formato da janela da moldura — dá pra conferir a
  pasta inteira de uma vez antes de processar. Tem um botão **"Girar 90°"**
  embaixo de cada miniatura pra corrigir fotos de lado individualmente (vale
  só pra aquela foto, tem prioridade sobre o campo de rotação geral).
- **Log**: o histórico do processamento (o que deu certo, o que falhou).

Cada foto é redimensionada para preencher a janela sem distorcer (corta o
excesso do centro, igual ao "preencher" do Smart Album).

**Rotação:** o programa usa os pixels da foto exatamente como estão no
arquivo — ele **não** confia na tag de orientação EXIF, porque fotos que já
passaram pelo WhatsApp costumam guardar uma tag velha/errada que não bate
mais com a imagem (isso foi confirmado testando com fotos reais: usar a
tag EXIF virava várias fotos de lado).

Nos modos **Máscara PSD** e **Grade simples**, o campo **Rotação das
fotos** já vem em **"Automática"** por padrão: cada foto é avaliada
sozinha — se ela é em pé (retrato), gira 270° (assim ela encaixa certo nos
gabaritos de polaroide, que são impressos deitados e cortados/girados
depois); se ela já é deitada (paisagem), **fica reta, sem girar** — não
faz sentido virar de lado uma foto que já veio horizontal. Isso resolve
pastas que misturam fotos de origens diferentes (retrato e paisagem juntas)
sem precisar mexer em nada.

Se quiser forçar um ângulo fixo pra pasta toda (0°/90°/180°/270°) em vez da
automática, é só trocar o campo. No **modo Medidas manuais** o padrão é
0° (sem rotação), já que esse modo não segue a convenção de impressão
rotacionada dos gabaritos de ímã.

Se mesmo assim **alguma foto específica** vier de lado (ex: uma foto
paisagem que na verdade precisava girar), corrija ela individualmente na
aba **"Todas as fotos"** (veja acima) — o ajuste manual ali tem prioridade
sobre a automática.

**Corte demais / cortando as pessoas:** isso normalmente não é a foto de
origem tendo um formato muito diferente da janela da moldura. Por exemplo,
uma foto quadrada (comum em fotos que já vieram cortadas em quadrado)
encaixada na moldura **Imã Horizontal** (janela bem larga, 9,18x5,30cm)
perde quase metade da altura no corte. Duas saídas pra isso:

- Conferir se o molde escolhido é mesmo o ideal pra aquele formato de foto
  (ex: a moldura **Imã Vertical**, mais próxima do quadrado, corta bem
  menos) — vale olhar a aba "Todas as fotos" antes de processar a pasta
  toda.
- Trocar o **Encaixe da foto na janela** pra **"Encaixar a foto inteira
  (com borda)"** (veja abaixo): a foto nunca é cortada, no lugar disso
  sobra uma borda da cor escolhida nos dois lados que não bate a proporção.

### Encaixe da foto na janela

- **Preencher e cortar o excesso**: a foto preenche a janela inteira sem
  sobrar nada, cortando o que não couber — é o comportamento de "preencher"
  do Smart Album, igual a uma polaroide de verdade.
- **Encaixar a foto inteira (com borda)**: a foto inteira aparece sem
  cortar nenhum pedaço; se a proporção não bater exatamente com a janela,
  sobra uma faixa da **cor da borda** (configurável, branco por padrão) de
  cada lado do eixo que sobrou. O tamanho final continua sendo exatamente
  o da janela/moldura — só muda se sobra foto ou se sobra borda.

**O programa escolhe o padrão sozinho conforme o produto**, porque cada um
tem uma prioridade diferente:

- **Imã/polaroide avulsa (1 foto por moldura)** — modo manual, ou máscara
  PSD com só 1 janela (ex: Imã Horizontal/Vertical): usa **"Preencher e
  cortar"**. É uma polaroide de verdade, não faz sentido sobrar borda
  branca extra além da moldura.
- **Folha com várias fotos** — modo Grade simples, ou máscara PSD com
  várias janelas (ex: Folha Imã 4x): usa **"Encaixar a foto inteira"**. Ali
  o risco de cortar alguém da foto é mais sério que sobrar uma borda.

Você pode trocar manualmente a qualquer momento — a escolha automática só
acontece ao trocar de modo ou carregar uma máscara/preset novo, pra não
atrapalhar um ajuste que você já fez na pasta atual.

## Como o cálculo da moldura funciona (modo manual)

A partir do tamanho total da moldura e do tamanho da janela da foto, o
programa calcula a diferença de largura e de altura. O lado com menor
diferença vira a borda fina (e fica igual nos três lados), e o lado com
maior diferença é onde entra a borda grossa (estilo "aba" da polaroid) —
você escolhe em qual dos dois lados desse eixo ela fica.

Isso significa que basta trocar as medidas na tela para gerar molduras
diferentes (outro tamanho de impressão, outro formato de álbum) sem precisar
mexer em nenhum arquivo de máscara.
