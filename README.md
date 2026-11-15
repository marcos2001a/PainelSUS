# Painel local de produção ambulatorial

MVP local para leitura dos DBCs `PASPYYMM[a-d].dbc`, agregação por CNES,
competência e procedimento e visualização em dashboard web.

## Requisitos

- Windows
- Python 3.12 ou 3.13
- Os arquivos em `C:\SUS\TABWIN\DADOS\PA 2025 e 2026`

O XAMPP não é necessário neste MVP. O backend é Python/FastAPI e a base de
análise é SQLite, mantida em `dashboard\data\producao.sqlite3`. O MariaDB pode
ser avaliado se a aplicação passar a atender usuários simultâneos em rede.

## Instalar e iniciar

1. Execute `install.bat`.
2. Execute `run.bat`.
3. Abra `http://127.0.0.1:8000`.
4. Clique em **Importar DBCs** na mensagem apresentada pelo painel.

## Produção hospitalar (SIH/SUS)

O menu **Prod. Hospitalar** consulta os arquivos reduzidos `RDSP*.dbc` do SIH/SUS.
Por padrão, os arquivos são procurados em `C:\SUS\TABWIN\DADOS\RD 2026`; a pasta
pode ser alterada com `TABWIN_RD_DATA_DIR`. Use **Importar DBCs RDSP** para importar
ou atualizar as competências disponíveis. O painel apresenta internações, valor
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

Para reduzir exposição de dados, o banco analítico **não armazena** CNS,
autorização, CID, município de residência ou demais dimensões individuais dos
registros DBC. Ele mantém somente somas por arquivo, CNES, competência e
código do procedimento. Os arquivos DBC são bases de origem e continuam no
diretório original.

## Acesso e proteção

O servidor inicia vinculado somente a `127.0.0.1`. Não o exponha diretamente à
rede local ou à internet. Acesso remoto requer autenticação, TLS, gestão de
segredos, autorização por usuário e uma implantação revisada; isso não faz
parte desta primeira versão.

## Configuração

As opções podem ser definidas por variável de ambiente:

- `TABWIN_PA_DATA_DIR`: diretório dos DBCs;
- `TABWIN_REFERENCE_DIR`: diretório que contém `CNESBR.dbf` e a pasta `DBF`;
- `TABWIN_ANALYTICS_DB`: localização do SQLite;
- `TABWIN_TEMP_DIR`: diretório de espaço temporário usado na expansão.

## Licença da dependência DBC

O decodificador `pyreaddbc` tem licença AGPL-3.0. Esta dependência foi escolhida
para o MVP porque já estava disponível no ambiente e leu com sucesso um DBC
local. Antes de redistribuir a aplicação ou oferecer acesso pela rede, revise
as obrigações dessa licença e publique o código-fonte correspondente quando
aplicável.
