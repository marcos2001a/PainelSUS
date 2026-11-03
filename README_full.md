# Painel de Produção Ambulatorial - Documentação Completa

## Visão Geral

Este projeto é um painel web para monitoramento e análise de produção ambulatorial do sistema SIA/SUS. Ele permite visualizar dados de produção por unidade de saúde, comparar períodos e analisar procedimentos e exames realizados.

## Estrutura do Projeto

```
/dashboard
├── app/                           # Código-fonte Python (FastAPI)
│   ├── __init__.py
│   ├── config.py                  # Configurações e caminhos de diretórios
│   ├── database.py               # Funções de conexão e schema do banco de dados
│   ├── ingest.py                 # Processamento de arquivos DBC
│   ├── main.py                   # API principal
│   └── periods.py                # Funções auxiliares de data/mês
├── static/                       # Arquivos estáticos (HTML, CSS, JS)
│   ├── index.html               # Página principal
│   ├── styles.css              # Estilos
│   └── dashboard.js            # Lógica do cliente
├── data/                        # Banco de dados SQLite
│   └── producao.sqlite3         # Banco de dados de produção
├── img/                         # Imagens
│   └── brasao.png               # Brasão do SUS (usado como logo e favicon)
├── .venv/                       # Ambiente virtual Python
├── requirements.txt             # Dependências do Python
├── README.md                    # Este documento
└── run.bat                      # Script de inicialização do Windows
```

## Requisitos Técnicos

### Backend (Python)
- **Framework**: FastAPI 0.115+
- **Servidor**: uvicorn 0.34+
- **Banco de dados**: SQLite 3.x
- **Linguagem**: Python 3.12+

### Frontend (JavaScript)
- **Framework**: Vanilla JavaScript (sem dependências externas)
- **HTML5**: Sematântica semântica
- **CSS3**: Estilos modernos com layout de grade responsivo
- **Navegador**: Compatível com Chrome, Firefox, Safari e Edge modernos

### Dependências

#### Python (`requirements.txt`)
```
fastapi>=0.115,<1
uvicorn[standard]>=0.34,<1
dbfread>=2.0.7,<3
pyreaddbc>=2.0.4,<3
```

#### Frontend
- Nenhum pacote de terceiros; todo o código é localizado

### Hardware e Ambiente
- **Sistema Operacional**: Windows 10/11, Linux, macOS
- **CPU**: Multi-core (para processamento paralelo)
- **Memória**: Mínimo 2 GB para o SQLite
- **Espaço em disco**: Mínimo 1 GB para arquivos DBC e banco de dados
- **Rede**: O servidor roda em `127.0.0.1` (localhost apenas para segurança)

## Esquema do Banco de Dados

### Tabelas Principais

#### `source_files`
| Coluna | Tipo | Descrição |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Chave primária auto-incrementada |
| `relative_path` | TEXT NOT NULL UNIQUE | Caminho relativo do arquivo DBC |
| `size_bytes` | INTEGER NOT NULL | Tamanho do arquivo em bytes |
| `modified_ns` | INTEGER NOT NULL | Timestamp de modificação em nanosegundos |
| `record_count` | INTEGER NOT NULL | Número de registros no arquivo |
| `imported_at` | TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP | Timestamp de importação |

#### `production`
| Coluna | Tipo | Descrição |
|--------|------|-------------|
| `source_file_id` | INTEGER NOT NULL | Referência para `source_files.id` |
| `cnes` | TEXT NOT NULL | CNES da unidade de saúde (7 dígitos) |
| `competence` | TEXT NOT NULL | Competência (mês) no formato YYYYMM |
| `procedure_code` | TEXT NOT NULL | Código do procedimento (até 10 dígitos) |
| `submitted_quantity` | INTEGER NOT NULL DEFAULT 0 | Quantidade antes da aprovação |
| `approved_quantity` | INTEGER NOT NULL DEFAULT 0 | Quantidade aprovada |
| `submitted_value_cents` | INTEGER NOT NULL DEFAULT 0 | Valor antes da aprovação (em centavos) |
| `approved_value_cents` | INTEGER NOT NULL DEFAULT 0 | Valor aprovado (em centavos) |

**Chave Primária Composta**: `(source_file_id, cnes, competence, procedure_code)`

#### `facilities`
| Coluna | Tipo | Descrição |
|--------|------|-------------|
| `cnes` | TEXT PRIMARY KEY | CNES da unidade de saúde (7 dígitos) |
| `name` | TEXT NOT NULL | Nome da unidade de saúde |

#### `procedures`
| Coluna | Tipo | Descrição |
|--------|------|-------------|
| `code` | TEXT PRIMARY KEY | Código do procedimento |
| `description` | TEXT NOT NULL | Descrição detalhada do procedimento |
| `source` | TEXT NOT NULL | Fonte do cadastro (ex: "TPROC.DBF") |

### Índices

- `idx_production_cnes_competence` : `(cnes, competence)` - Consultas rápidas por unidade e período
- `idx_production_competence` : `(competence)` - Agregação por competência |
- `idx_production_procedure` : `(procedure_code)` - Filtragem por tipo de procedimento

## APIs do Backend (`main.py`)

### Endpoints Gerais

#### `/api/status`
**GET** - Retorna status da importação e estatísticas do banco de dados

```json
{
  "data_directory_exists": true,
  "available_files": 42,
  "imported_files": 15,
  "source_records": 3450000,
  "units": 2500,
  "groups": 1800,
  "first_competence": "202501",
  "last_competence": "202512",
  "import": {
    "running": false,
    "current": 0,
    "total": 0,
    "file": null,
    "status": "idle",
    "message": null,
    "result": null
  }
}
```

#### `/api/units`
**GET** - Retorna unidades de saúde filtradas por CNES ou nome

Parâmetros:
- `q` (opcional): Termo de busca para CNES ou nome

```json
[
  {"cnes": "2786826", "name": "HOSPITAL DARWIN"},
  {"cnes": "2786729", "name": "CLINICA SAÚDE"},
  ...
]
```

#### `/api/dashboard`
**GET** - Retorna dados do dashboard para uma unidade e período específicos

Parâmetros:
- `cnes` (obrigatório): CNES da unidade (7 dígitos)
- `start` (obrigatório): Mês inicial no formato YYYY-MM (ex: "2025-01")
- `end` (obrigatório): Mês final no formato YYYY-MM (ex: "2025-12")

```json
{
  "cnes": "2786826",
  "facility_name": "HOSPITAL DARWIN",
  "period": {"start": "202501", "end": "202512"},
  "comparison_period": {"start": "202401", "end": "202412"},
  "summary": {
    "approved_quantity": 125430,
    "approved_value_cents": 245670000,
    "submitted_quantity": 132100,
    "submitted_value_cents": 258920000,
    "approved_change": {"difference": -5730, "percentage": -4.3},
    "previous_approved_quantity": 131160,
    "active_procedures": 842
  },
  "series": [
    {
      "month": "202501",
      "label": "Jan/2025",
      "approved_quantity": 10500,
      "previous_approved_quantity": 9800,
      "approved_value_cents": 20500000,
      "previous_approved_value_cents": 19200000
    },
    ...
  ],
  "procedures": [
    {
      "code": "0101010010",
      "description": "CONSULTA MÉDICA - CLINICO GERAL",
      "type": "procedimento",
      "approved_quantity": 8500,
      "previous_approved_quantity": 8200,
      "difference": 300,
      "percentage": 3.7,
      "approved_value_cents": 17000000
    },
    ...
  ],
  "top_procedures": [...],
  "increases": [...],
  "decreases": [...]
}
```

#### `/api/import`
**POST** - Inicia a importação de arquivos DBC na pasta de dados

```json
{
  "status": "queued"
}
```

## APIs do Frontend (`dashboard.js`)

### Estado Principal (`state`)
```javascript
const state = {
  status: null,                    // Status do servidor
  units: [],                       // Lista de unidades
  unitLabels: new Map(),            // Mapa de rótulos para unidades
  selectedUnit: null,              // Unidade selecionada
  dashboard: null,                 // Dados do dashboard
  comparePrevious: false,          // Se deve comparar com período anterior
  activeTab: "procedimento",       // Tab ativa ("procedimento" ou "exame")
  page: 1,                         // Página atual da paginação
  pageSize: 10,                     // Itens por página
  visibleProcedures: 12,           // Contador de procedimentos visíveis
  // ... outros campos
};
```

### Interface do Usuário

#### Painel de Filtros
- **Unidade de Saúde**: Campo de busca com autocomplete para selecionar CNES ou nome
- **Competência Inicial/Final**: Seletores de mês (MMAAAA)
- **Comparar com Período Anterior**: Checkbox para incluir dados do mesmo período no ano anterior
- **Botão Aplicar Filtros**: Carrega os dados do dashboard

#### Grid de Métricas
Mostra indicadores principais:
- Procedimentos aprovados
- Valor aprovado
- Procedimentos diferentes (códigos únicos)
- Quantidade apresentada

#### Painel de Evolução
Gráfico de linha mostrando:
- Evolução mensal de procedimentos aprovados
- Opcionalmente inclui linha de comparação com o ano anterior

#### Painel de Destaques
Top 4 procedimentos com maiores aumentos e top 4 com maiores reduções

#### Painel de Procedimentos/Exames
- **Abas**: "Procedimentos" e "Exames" para separar os dois tipos
- **Busca e Ordenação**: Busca por código/descrição e ordenação por volume/aumento/redução
- **Paginação**: Navegação entre páginas de 10 itens cada
- **Tabelas**: Exibem código, descrição, quantidade aprovada, variação e valor aprovado

### Funcionalidades Avançadas

#### Classificação Automática de Procedimentos
O backend classifica procedimentos automaticamente usando palavras-chave:

**Palavras-chave para "Exames"**:
- "exame", "raio x", "radiografia", "ultrasson", "ultrass", "tomografia", "ressonancia", "eletro", "doppler", "endoscopia", "colonoscopia", "mamografia", "densitom", "cintilograf", "dosagem", "glicose", "hemograma", "coagulograma", "urina i", "urina ii", "espirometria", "audiometria", "eletrocardiograma", "eletroencefalograma", "biopsia", "citologia", "papanicolau", "cultura", "antigrama", "sorologia", "virologia", "bacteriologia", "parasitologia", "micologia", "citogenet", "cariotipo", "hla", "tipific", "crossmatch"

#### Persistência de Estado
- **LocalStorage**: Salva preferências de abas e página da paginação
- **Sincronização de estado**: Mantém estado consistente entre components

#### Importação de Dados
- **Upload de DBC**: Interface para importar arquivos DBC brutos
- **Importação em Segundo Plano**: Processa arquivos sequencialmente sem bloquear a interface do usuário
- **Monitor de Progresso**: Mostra progresso de importação com barra de progresso e mensagens

## Fluxo de Importação

1. **Configuração Inicial**: 
   - A pasta de dados é configurada via variável de ambiente `TABWIN_PA_DATA_DIR` (padrão: `C:\SUS\TABWIN\DADOS\PA 2025 e 2026`)
   - O banco de dados SQLite é criado em `dashboard\data\producao.sqlite3`

2. **Primeira Importação**:
   - Clique em "Importar DBCs" na interface
   - Os arquivos DBC são expandidos temporariamente usando `pyreaddbc`
   - Os dados são agregados por CNES, competência e procedimento
   - Os cadastros de unidades e procedimentos são carregados dos arquivos DBF de referência

3. **Importações Subsequentes**:
   - Arquivos com mesmo tamanho e timestamp são ignorados
   - Apenas alterações são processadas (atualizações incrementais)

## Como Executar

### Requisitos de Instalação

1. **Instale o Python 3.12+**
2. **Clone o repositório**:
   ```bash
   git clone <url-do-repositorio>
   cd SUS-TABWIN/dashboard
   ```

3. **Crie ambiente virtual** (recomendado):
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # Linux/macOS:
   source .venv/bin/activate
   ```

4. **Instale dependências**:
   ```bash
   pip install -r requirements.txt
   ```

5. **Execute o servidor**:
   ```bash
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

### Scripts de Wrapper Windows (`run.bat`)

Para convenience no Windows, há um script `run.bat`:

```batch
@echo off
.
venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Acesso à Interface

1. **Abra o navegador**
2. **Navegue até**: `http://127.0.0.1:8000`
3. **Realize importação** (se necessário): Clique em "Importar DBCs"
4. **Selecione uma unidade** e **escolha um período** para visualizar os dados

## Arquitetura do Sistema

### Design Multicamadas

1. **Camada de Persistência (SQLite)**:
   - Banco de dados relacionais para armazenamento eficiente
   - Índices para consultas rápidas
   - Constraints de integridade referencial

2. **Camada de Aplicação (FastAPI)**:
   - APIs REST que expõem dados de forma estruturada
   - Validação de parâmetros com FastAPI
   - Processamento assíncrono para importações

3. **Camada de Apresentação (Frontend)**:
   - Interface de usuário responsiva e acessível
   - Componentes de interface de usuário React-like (sem dependência)
   - Dashboard interativo com gráficos e tabelas

### Protocolos de Comunicação

- **HTTP/HTTPS**: APIs REST
- **WebSocket** (opcional): Para atualizações em tempo real futuras
- **CORS**: Restrito a origens locais para segurança

### Segurança

1. **Rede**: O servidor só escuta em `127.0.0.1`
2. **Autenticação**: Não implementada no MVP (proteção por firewall/rede)
3. **Validação**: Validação rigorosa de parâmetros em todas as APIs
4. **Sanitização**: Escaped de HTML em todo o frontend

### Gerenciamento de Estado

- **Frontend**: Estado simples baseado em objetos JavaScript, sincronizado entre components
- **Backend**: Estado em memória para uploads de arquivos, persistido em SQLite para dados permanentes
- **Reset**: Ferramentas de linha de comando para corrigir dados corrompidos

## Recursos e Considerações Futuras

### Recursos Atuais
- Listagem e filtragem de unidades de saúde
- Seleção de período e comparação com período anterior
- Gráfico de linha para evolução mensal
- Classificação automática de procedimentos em "exames" e "procedimentos"
- Tabelas paginadas com busca e ordenação
- Importação de dados DBC
- Exportação CSV de procedimentos

### Recursos Futuros Sugeridos
- **Acesso Multiusuário**: Contas de usuário e permissões
- **Autenticação**: Login OAuth2/JWT
- **Configurações Personalizadas**: Widgets de dashboard ajustáveis pelo usuário
- **Visualizações Avançadas**: Gráficos com mais dimensões
- **API Pública**: Consumível por outros sistemas
- **Alertas**: Notificações para mudanças significativas
- **Logs de Auditoria**: Rastreabilidade completa de todas as operações

### Escala e Desempenho

- **Desempenho Atual**: Pronto para até ~10.000 unidades e milhões de registros
- **Otimizações de Escala**:
  - Índices no SQLite para consultas rápidas
  - Agregação de dados no momento da importação
  - Limpeza de registros antigos (mecanismo futuro)

## Configuração

### Variáveis de Ambiente

| Variável | Valor Padrão | Descrição |
|----------|---------------|-------------|
| `TABWIN_PA_DATA_DIR` | `C:\SUS\TABWIN\DADOS\PA 2025 e 2026` | Diretório contendo arquivos DBC |
| `TABWIN_REFERENCE_DIR` | `C:\SUS\TABWIN` | Diretório com arquivos de referência DBF |
| `TABWIN_ANALYTICS_DB` | `dashboard\data\producao.sqlite3` | Caminho para o banco de dados SQLite |
| `TABWIN_TEMP_DIR` | `tempfile.gettempdir()` | Diretório temporário para expansão de DBC |

### Arquivo de Configuração

Para configurações mais complexas, um arquivo de configuração JSON pode ser adicionado no futuro.

## Testes

### Testes de Unidade
- **Python**: pytest (planejado)
- **Frontend**: Jest (planejado)

### Teste Manual
1. **Status**: Acesse `/api/status` para verificar a saúde do sistema
2. **Unidades**: `/api/units?q=2786` para listar unidades por CNES
3. **Dashboard**: Use parâmetros válidos para testar a lógica do dashboard
4. **Importação**: Inicie importação e monitore progresso

## Manutenção

### Backup e Recuperação

#### Backup
```bash
# Fazer backup do banco de dados
copy dashboard\data\producao.sqlite3 backup_$(date +%Y%m%d_%H%M%S).sqlite3

# Fazer backup de arquivos DBC (se armazenados em outra localização)
copy C:\SUS\TABWIN\DADOS\PA\*.* backup_dbc_$(date +%Y%m%d_%H%M%S)\
```

#### Recuperação
```bash
# Restaurar banco de dados
C:\> sqlite3 dashboard\data\producao.sqlite3 ".read backup.sql"
```

### Solução de Problemas

#### Erros Comuns

**"Pasta de DBC não encontrada"**:
- Verifique se a variável de ambiente `TABWIN_PA_DATA_DIR` está correta
- Confirme se a pasta existe e contém arquivos DBC

**"Nenhuma unidade com produção importada"**:
- Execute uma importação através da interface ou diretamente:
  ```bash
  .\venv\Scripts\python.exe -m app.ingest --limit-files 1
  ```

**"Erro no servidor ao iniciar"**:
- Certifique-se de que todas as dependências estão instaladas
- Verifique conflitos de porta (use uma porta diferente se 8000 estiver em uso)

## Agradecimentos

- **pyreaddbc**: Biblioteca para ler arquivos DBC
- **dbfread**: Biblioteca para ler arquivos DBF
- **FastAPI & uvicorn**: Framework web e servidor
- **Community**: Testadores beta e contribuidores

## Licença

Este é um projeto de código aberto. Veja o arquivo LICENSE para detalhes.

---

**Documentação gerada automaticamente pelo assistente Kilo**
**Última atualização**: 2026-11-02
**Versão**: 0.1.0