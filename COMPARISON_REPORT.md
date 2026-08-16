# Comparação: Repositório Atual vs. Repositório Oficial

**Data:** 2026-08-16  
**Repositório Atual:** https://github.com/brendoncarvalho/agent-platform-railway  
**Repositório Oficial:** https://github.com/agno-agi/agentos-railway.git

---

## 📊 Resumo de Mudanças

- **43 arquivos modificados**
- **2,488 inserções** | **1,357 deletions**
- **8 arquivos adicionados na versão oficial**
- **7 arquivos removidos na versão oficial**
- **28 arquivos modificados**

---

## ✅ Arquivos Adicionados na Versão Oficial

| Arquivo | Descrição |
|---------|-----------|
| `.agents/skills/create-agent/SKILL.md` | Nova skill para criar agentes (238 linhas) |
| `.agents/skills/create-evals/SKILL.md` | Nova skill para criar evals (86 linhas) |
| `.agents/skills/deploy-platform/SKILL.md` | Nova skill para deploy da plataforma (124 linhas) |
| `.agents/skills/setup-platform/SKILL.md` | Nova skill para setup da plataforma (108 linhas) |
| `agents/chief.py` | Novo agente Chief (159 linhas) |
| `agents/platform_manager.py` | Novo agente Platform Manager (192 linhas) |
| `scripts/mcp_check.sh` | Script de verificação de MCP (141 linhas) |
| `scripts/railway/down.sh` | Script para desativar Railway (117 linhas) |

---

## ❌ Arquivos Removidos na Versão Oficial

| Arquivo | Descrição |
|---------|-----------|
| `.agents/skills/create-new-agent/SKILL.md` | Substituída por `create-agent/SKILL.md` |
| `agents/code_search.py` | Removido (agent de busca em código) |
| `agents/crm_note_autofix.py` | Removido (agent CRM) |
| `agents/general_chat.py` | Removido (chat geral) |
| `agents/web_search.py` | Removido (busca web) |
| `compose.coolify.yaml` | Removido (compose alternativo) |
| `evals/dotenv.py` | Removido (utilitário de dotenv) |

---

## 🔄 Arquivos Modificados (Principais Mudanças)

### **app/main.py**
- **+35/-7 linhas**: Mudanças significativas na arquitetura principal
- Refatoração para suportar novos agentes (Chief, Platform Manager)
- Ajustes no AgentOS

### **agents/agent_builder.py**
- **+49/-31 linhas**: Expansão de capacidades
- Integração com AgentOSTools
- Mudanças nas instruções

### **app/schedules.py**
- **+64/-20 linhas**: Novo sistema de agendamento
- Maior controle sobre workflows

### **evals/cases.py**
- **+243/-97 linhas**: Expansão da suite de avaliação
- Mais casos de teste e cobertura

### **AGENTS.md** (Documentação)
- **+107/-46 linhas**: Documentação atualizada
- Refletindo novas arquiteturas e agentes

### **README.md**
- **+100/-81 linhas**: Documentação melhorada
- Atualizações gerais

### **pyproject.toml**
- **+14/-12 linhas**: Atualização de dependências

### **requirements.txt**
- **+143/-58 linhas**: Mudanças significativas nas dependências
- Agno 2.8.5 final (release completa)

### **requirements.txt** (Destaques)
- Agora usa `agno==2.8.5` final em vez de versão pinned temporária
- Novas dependências para suportar novos agentes

---

## 🎯 Mudanças Principais na Arquitetura

### **1. Consolidação de Agentes**
- ❌ Removidos: `web_search`, `code_search`, `crm_note_autofix`, `general_chat`
- ✅ Adicionados: `chief.py`, `platform_manager.py`
- O novo agente `platform_manager.py` usa **AgentOSTools** para operações de plataforma

### **2. Nova Skill: `create-agent`**
- Substitui `create-new-agent/SKILL.md`
- Refatorada para melhor usabilidade

### **3. Novas Skills de Plataforma**
- `create-evals/SKILL.md`: Para criar casos de avaliação
- `deploy-platform/SKILL.md`: Para deploy automático
- `setup-platform/SKILL.md`: Para configuração inicial

### **4. Melhorias no Sistema de Agendamento**
- Mais workflows integrados
- Melhor tratamento de schedules
- Novos endpoints para deployment

### **5. Hardening de Agentes**
- Instruções dos agentes foram endurecidas (95-probe campaign)
- Implementação de "Learning Machine" compartilhada entre agentes
- Melhor reflexibilidade na melhoria dos agentes

---

## 📦 Mudanças de Dependências (Highlights)

### **Versão Agno**
- **Antes**: Pinned temporário (PR #9185 @ 335ab01)
- **Depois**: `agno==2.8.5` (release final)

### **Scripts**
- Novo: `mcp_check.sh` para verificação de MCP servers
- Novo: `scripts/railway/down.sh` para limpeza de Railway
- Atualizado: `scripts/generate_requirements.sh` com 14 linhas de novo conteúdo

---

## 🔧 Configurações Alteradas

### **compose.yaml**
- **-2 linhas**: Pequenas otimizações

### **.dockerignore e .gitignore**
- **+5 linhas cada**: Adicionados novos padrões de ignore

### **Dockerfile**
- **+1/-1 linhas**: Pequeno ajuste

### **example.env**
- **+20/-26 linhas**: Variáveis de ambiente refatoradas
- Novas env vars para novos agentes

---

## 🚀 Commits Recentes (20 mais recentes da versão oficial)

Alguns destaques:
1. **feat(deploy-platform)**: Branch para redeploy quando plataforma já está live
2. **fix(deploy-platform)**: Imprimir MCP connect secret
3. **docs: README copy pass** — API + MCP server tagline
4. **fix: review-pass hardening** — sweep guards e fixture rules
5. **feat(agents)**: Uma "self" compartilhada entre agentes — builder e PM usam LearningMachine
6. **fix(skills): improve-agent mines real usage** para probes

---

## 🔍 Recomendações

### ✅ O que Fazer

1. **Se você quer atualizar para a versão oficial:**
   ```bash
   git merge official/main
   ```
   Há conflitos esperados (agentes removidos, novos arquivos)

2. **Revisar as mudanças:**
   - Os novos agentes `chief.py` e `platform_manager.py` usam AgentOSTools
   - As skills foram reorganizadas e melhoradas
   - Dependências foram atualizadas para agno 2.8.5

3. **Testar localmente:**
   ```bash
   docker compose up -d --build
   python -m evals --profile smoke
   ```

### ⚠️ Pontos de Atenção

- **Agentes Removidos**: Se você depende de `web_search`, `code_search`, etc., precisará adaptá-los
- **Breaking Changes**: A arquitetura de agents mudou significativamente
- **Testes**: Recomenda-se rodar `python -m evals --profile release` após merge
- **Dependências**: Verifique se agno 2.8.5 é compatível com seu setup

---

## 📝 Próximos Passos

```bash
# Ver diff detalhado de um arquivo específico
git diff main official/main -- agents/chief.py

# Ver um arquivo específico da versão oficial
git show official/main:agents/chief.py

# Aplicar mudanças seletivas
git cherry-pick <commit-hash>

# Merge completo
git merge official/main
```

---

**Gerado automaticamente**
