# Smart Leads - Backend

API para extração de contatos do Google Maps (Google Local) em tempo real com paginação automática.

## Funcionalidades

- Extração automática de leads do Google Local (LCL)
- **Paginação automática** - busca em múltiplas páginas até atingir a quantidade
- Comunicação em tempo real via WebSocket (Socket.io)
- Remoção automática de duplicatas
- Progress tracking em tempo real
- API REST com Express
- **🛡️ Sistema Anti-Detecção Avançado** - evita RECAPTCHA e bloqueios
  - Stealth mode com puppeteer-extra
  - Comportamento humano simulado (mouse, scroll, delays)
  - User agents realistas e rotativos
  - Fingerprinting avançado
- **⚡ Sistema de Delays Adaptativos** - rápido mas seguro
  - Acelera automaticamente quando seguro
  - 3x mais rápido que versão anterior
  - Mantém segurança com detecção inteligente

## Tecnologias

- Node.js
- Express.js
- Socket.io (WebSocket)
- Puppeteer Extra (Web Scraping com Stealth)
- Puppeteer Stealth Plugin (Anti-detecção)
- User Agents (Rotação de navegadores)
- CORS habilitado

## Instalação

### Pré-requisitos

- Node.js (versão 14 ou superior)
- npm ou yarn

### Passos

1. Instale as dependências:
```bash
npm install
```

2. Inicie o servidor:
```bash
npm start
```

3. Acesse no navegador:
```
http://localhost:3000
```

## Como funciona

1. Cliente conecta via WebSocket
2. Envia evento `start-extraction` com parâmetros (nicho, região, quantidade)
3. Backend usa Puppeteer para:
   - Acessar Google Local Search (tbm=lcl)
   - **Buscar em múltiplas páginas** até atingir quantidade solicitada
   - Extrair nome e telefone de cada estabelecimento
4. Envia dados progressivamente via WebSocket
5. Remove duplicatas automaticamente

## Paginação

O sistema busca automaticamente em várias páginas:
- Máximo: 10 páginas
- Para quando atinge a quantidade solicitada
- Para se não encontrar mais resultados
- Remove duplicatas entre páginas

Exemplo: Ao solicitar 50 leads, o sistema pode buscar 3-5 páginas do Google para coletar os resultados.

## Exemplo de Uso

**Input:**
- Nicho: Dentista
- Região: Belo Horizonte
- Quantidade: 30

O sistema irá:
1. Pesquisar "Dentista em Belo Horizonte" no Google Maps
2. Extrair informações de 30 estabelecimentos
3. Retornar: nome, telefone e endereço de cada um

## API WebSocket

### Eventos do Cliente

**start-extraction**
```javascript
socket.emit('start-extraction', {
  nicho: 'dentista',
  regiao: 'são paulo',
  quantidade: 50
});
```

### Eventos do Servidor

**progress**
```javascript
{
  status: 'Buscando página 1...',
  percent: 10
}
```

**new-lead**
```javascript
{
  nome: 'Clínica Exemplo',
  telefone: '(11) 98765-4321',
  endereco: 'Não disponível',
  index: 1
}
```

**extraction-complete**
```javascript
{
  success: true,
  message: 'Extração concluída!'
}
```

**extraction-error**
```javascript
{
  success: false,
  message: 'Erro: Nenhum resultado encontrado'
}
```

## API REST

### GET /api/health

Verifica status do servidor.

```json
{
  "status": "OK",
  "message": "Servidor rodando!"
}
```

## Estrutura do Projeto

```
Smart Leads 2/
├── public/
│   ├── index.html      # Interface web
│   ├── style.css       # Estilos
│   └── script.js       # Lógica frontend
├── services/
│   └── scraper.js      # Serviço de scraping
├── server.js           # Servidor Express
├── package.json        # Dependências
└── README.md           # Documentação
```

## Desenvolvimento

Para desenvolvimento com auto-reload:

```bash
npm run dev
```

## 🛡️ Sistema Anti-Detecção

O sistema implementa várias técnicas para evitar RECAPTCHA e detecção de bot:

### 🚨 SE VOCÊ ESTÁ COM RECAPTCHA AGORA

**Leia**: [SOLUCAO_RECAPTCHA.md](./SOLUCAO_RECAPTCHA.md) - Guia completo de solução

**Resumo rápido**:
1. ✋ **PARE** - Aguarde 1-2 horas
2. 🔄 **TROQUE O IP** - Reinicie roteador ou use proxy
3. ⚙️ **Configure .env** com `HEADLESS=false`
4. 🧹 **Limpe cookies**: `rm -f .cookies.json`
5. 🚀 **Teste com 10 contatos** primeiro

### Técnicas Implementadas

#### ✅ Detecção Automática de RECAPTCHA
- Detecta e para automaticamente se encontrar RECAPTCHA
- Salva screenshot para debug
- Mostra instruções de como resolver

#### ✅ Stealth Mode Avançado
- Puppeteer-extra com plugin stealth
- Remove todos indicadores de automação
- Passa em testes de detecção de bots

#### ✅ Comportamento Humano Realista
- **Movimento de mouse**: 2-4 movimentos aleatórios por página
- **Scroll gradual**: Com volta para cima (comportamento humano)
- **Cliques aleatórios**: 30% de chance de clicar na página
- **Delays variados**: 5-10s entre páginas (configurável)

#### ✅ Sessões Persistentes
- Salva cookies em `.cookies.json`
- Reutiliza sessão (parece usuário retornando)
- Estabelece sessão no google.com.br primeiro

#### ✅ Suporte a Proxy
- Configure via variável `PROXY_URL` no .env
- Suporta HTTP e SOCKS5
- Essencial se estiver bloqueado

#### ✅ Modo Não-Headless
- Configure `HEADLESS=false` no .env
- Navegador visível = muito mais difícil de detectar
- **Recomendado se estiver enfrentando RECAPTCHA**

### Configuração Anti-RECAPTCHA

Crie arquivo `.env` com:

```bash
# Navegador visível (mais seguro)
HEADLESS=false

# Delays aumentados
MIN_PAGE_DELAY=5000
MAX_PAGE_DELAY=10000

# Proxy (se tiver)
# PROXY_URL=http://usuario:senha@proxy.com:8080
```

### Recomendações de Uso
- ✅ Máximo 10-30 contatos por execução (se estiver com problemas)
- ✅ Aguardar 30-60 minutos entre buscas
- ✅ Variar nichos e regiões
- ✅ Usar em horários comerciais (9h-18h)
- ❌ Não fazer requisições em massa
- ❌ Não repetir mesma busca seguida

### Documentação Completa

📖 **[SOLUCAO_RECAPTCHA.md](./SOLUCAO_RECAPTCHA.md)** - Resolver RECAPTCHA atual

📖 **[ANTI_DETECTION.md](./ANTI_DETECTION.md)** - Técnicas anti-detecção detalhadas

⚡ **[VELOCIDADE_OTIMIZADA.md](./VELOCIDADE_OTIMIZADA.md)** - Sistema de delays adaptativos

## ⚡ Performance Otimizada

O sistema usa **delays adaptativos** que aceleram automaticamente:

### Tempos Estimados

| Contatos | Tempo | Velocidade |
|----------|-------|------------|
| 10 contatos | 8-15s | ⚡⚡⚡ |
| 30 contatos | 15-25s | ⚡⚡⚡ |
| 50 contatos | 20-35s | ⚡⚡ |
| 100 contatos | 40-70s | ⚡ |

### Como Funciona

- **Páginas 1-2**: 3-5s (cauteloso)
- **Páginas 3-5**: 2.5-4s (moderado)
- **Páginas 6+**: 2-3.5s ⚡ (acelerado!)

**Resultado**: 3x mais rápido que versão anterior, mantendo segurança!

## Observações Importantes

- ⚡ **Sistema otimizado**: ~3-5s por página com delays adaptativos
- O Google Maps pode ter limitações de taxa (rate limiting)
- Alguns estabelecimentos podem não ter telefone público disponível
- Recomenda-se usar com moderação para evitar bloqueios
- 🛡️ **Detecção automática de RECAPTCHA** - para e alerta se detectar

## Limitações

- Máximo de 100 contatos por extração
- Depende da estrutura HTML do Google Maps (pode quebrar se o Google mudar o layout)
- Alguns dados podem aparecer como "Não disponível" se não estiverem públicos

## Melhorias Futuras

- [ ] Sistema de filas para múltiplas extrações
- [ ] Cache de resultados
- [ ] Filtros avançados (rating, horário, etc)
- [ ] Exportação em outros formatos (Excel, JSON)
- [ ] Histórico de extrações
- [ ] Autenticação de usuários

## Licença

Este projeto é apenas para fins educacionais. Use com responsabilidade e respeite os Termos de Serviço do Google.

## Suporte

Para dúvidas ou problemas, abra uma issue no repositório.
