# Painel local de produção ambulatorial

MVP local para leitura dos DBCs `PASPYYMM[a-d].dbc`, visualização da produção
por CNES, competência e procedimento e relatórios de perfil por idade, CID,
sexo e raça/cor no menu **Diversos**.

## Requisitos

- Windows 10/11 ou Linux (Debian/Ubuntu e derivados, Fedora/RHEL ou Arch Linux)
- Python 3.12 ou 3.13
- DBCs ambulatoriais na pasta `DADOS/PA 2025 e 2026`, ao lado da pasta do
  projeto (no Windows: `C:\SUS\TABWIN\DADOS\PA 2025 e 2026`)

O XAMPP não é necessário neste MVP. O backend é Python/FastAPI e a base de
análise é SQLite, mantida em `dashboard\data\producao.sqlite3`. O MariaDB pode
ser avaliado se a aplicação passar a atender usuários simultâneos em rede.

## Instalar e iniciar

Execute os comandos na pasta raiz do projeto.

### Windows

1. Execute `install\install.bat`.
2. Execute `run.bat`.
3. Abra `http://127.0.0.1:8000`.
4. Clique em **Importar DBCs** para carregar os arquivos ambulatoriais.

O instalador usa Python 3.12 ou 3.13 se já estiver instalado. Caso contrário,
executa `install\python-3.13.12-amd64.exe` em modo silencioso e adiciona o
Python ao PATH do usuário.

### Linux

O instalador identifica Debian/Ubuntu e derivados, Fedora/RHEL ou Arch Linux,
instala as dependências do sistema e configura o ambiente virtual e os pacotes
Python. É necessário que a distribuição forneça Python 3.12 ou 3.13; se não
fornecer, o instalador informa o problema e encerra sem criar um ambiente
incompatível.

```bash
bash install/install.sh
bash install/start.sh
```

Para parar ou reiniciar a aplicação:

```bash
bash install/stop.sh
bash install/restart.sh
```

Abra `http://127.0.0.1:8000` e clique em **Importar DBCs** na mensagem
apresentada pelo painel.

Os scripts Linux gravam o log e o PID em `data/dashboard.log` e
`data/dashboard.pid`. Consulte [COMO_RODAR_LINUX.txt](./COMO_RODAR_LINUX.txt)
para detalhes de instalação e operação no Linux.

## Banco de dados em uma instalação nova

A pasta `data/` e os bancos SQLite são ignorados pelo Git. Ao iniciar a
aplicação em um clone novo, ela cria `data/producao.sqlite3` e as tabelas
necessárias, mas o banco começa vazio. Importe os DBCs para carregar os dados;
o banco de outra instalação deve ser transferido separadamente se for
necessário preservar dados já importados.

## Produção hospitalar (SIH/SUS)

O menu **Prod. Hospitalar** consulta os arquivos reduzidos `RDSP*.dbc` do SIH/SUS.
Na importação, somente os registros cujos CNES constam em
`CNES_TAUBATE_HOSPITALAR.txt` são incluídos. A **Visão geral** usa a lista
`CNES_TAUBATE.txt`; cada arquivo contém CNES e nome, com cabeçalho `CNES` na
primeira coluna. Alterações nos códigos dessas listas fazem os DBCs serem
reprocessados na próxima importação.
Clique em **Importar DBCs RDSP** e selecione um ou mais arquivos `RDSPaaaa.dbc`
no computador. Os arquivos selecionados são copiados para `data/hospital_uploads`
dentro do projeto e somente essa seleção é importada. A pasta configurada por
`TABWIN_RD_DATA_DIR` continua disponível para importações por linha de comando.
O painel apresenta internações, valor
total (`VAL_TOT`), óbitos, permanência e procedimentos realizados, com comparação
anual opcional. O SQLite guarda somente agregados por CNES, competência e
procedimento; os campos identificadores dos registros de AIH não são persistidos.

A primeira importação lê os DBCs sequencialmente. Cada arquivo é expandido
temporariamente e removido ao terminar; os DBCs originais não são alterados.
Os imports já concluídos são reutilizados quando tamanho e data de modificação
do arquivo não mudam. Se precisar reprocessar uma fonte, altere o arquivo ou
remova apenas a linha correspondente em `source_files` e os grupos associados
na base SQLite.

Para processar um único arquivo durante validação:

```powershell
.\.venv\Scripts\python.exe -m app.ingest --limit-files 1
```

Para executar a importação completa fora da interface:

```powershell
.\.venv\Scripts\python.exe -m app.ingest
```

## Dados e métricas

- A competência temporal usa `PA_MVM`.
- A unidade é `PA_CODUNI` (CNES); o nome é associado quando encontrado no
  cadastro local `CNESBR.dbf`.
- Os procedimentos usam `PA_PROC_ID`; descrições são associadas,
  preferencialmente, a `DBF\TPROCUNI.DBF` e `DBF\TPROC10.DBF`.
- Quantidade aprovada/apresentada usa `PA_QTDAPR`/`PA_QTDPRO`.
- Valor aprovado/apresentado usa `PA_VALAPR`/`PA_VALPRO`, armazenado em
  centavos inteiros para evitar erros de arredondamento.
- A comparação desloca o intervalo selecionado em 12 meses.
- O painel SIA calcula as taxas de aprovação de quantidade (`PA_QTDAPR` ÷
  `PA_QTDPRO`) e valor (`PA_VALAPR` ÷ `PA_VALPRO`) por mês e no período; a
  comparação anual exibe a diferença das taxas em pontos percentuais.
- No SIH, o valor médio por AIH é `VAL_TOT` ÷ internações, com variação em
  relação ao mesmo período do ano anterior. A tabela por procedimento
  apresenta mortalidade (óbitos ÷ internações) e permanência média
  (`DIAS_PERM` ÷ internações); taxas sem denominador são exibidas como
  indisponíveis.

Para reduzir a exposição de dados, o banco **não armazena** CNS, autorização
ou município de residência. Além dos totais por arquivo, CNES, competência e
procedimento, a opção **Diversos** guarda somente quantidades agregadas por
idade registrada, sexo, raça/cor e CID; nenhum registro individual é exibido.
Essas dimensões podem ser sensíveis, especialmente em grupos pequenos. Os
arquivos DBC são bases de origem e continuam no diretório original. Após a
atualização, arquivos importados anteriormente são reprocessados na próxima
importação para preencher os novos agregados.

## Acesso e proteção

O servidor inicia vinculado somente a `127.0.0.1`. Não o exponha diretamente à
rede local ou à internet. Acesso remoto requer autenticação, TLS, gestão de
segredos, autorização por usuário e uma implantação revisada; isso não faz
parte desta primeira versão.

## Configuração

As seguintes opções podem ser definidas por variável de ambiente:

- `TABWIN_RD_DATA_DIR`: diretório dos DBCs hospitalares usados em importações
  por linha de comando;
- `TABWIN_REFERENCE_DIR`: diretório que contém `CNESBR.dbf` e a pasta `DBF`;
- `TABWIN_TEMP_DIR`: diretório de espaço temporário usado na expansão.

Os DBCs ambulatoriais são procurados em `DADOS/PA 2025 e 2026`, ao lado da
pasta do projeto. O banco SQLite padrão fica em `data/producao.sqlite3`.

## Licença da dependência DBC

O decodificador `pyreaddbc` tem licença AGPL-3.0. Esta dependência foi escolhida
para o MVP porque já estava disponível no ambiente e leu com sucesso um DBC
local. Antes de redistribuir a aplicação ou oferecer acesso pela rede, revise
as obrigações dessa licença e publique o código-fonte correspondente quando
aplicável.
