# 🚨 SOLUÇÃO PARA RECAPTCHA ATUAL

Se você está vendo RECAPTCHA **AGORA**, siga este guia passo a passo.

## ⚡ Soluções Imediatas (faça AGORA)

### 1. **PARE TUDO** ✋
- Não tente rodar o programa novamente por pelo menos 1-2 horas
- Cada tentativa adicional piora o bloqueio

### 2. **Troque seu IP** 🔄

#### Opção A - Reiniciar Roteador (mais fácil)
```bash
# Desligue o roteador por 5 minutos
# Ligue novamente
# Verifique se o IP mudou: https://meuip.com.br
```

#### Opção B - Usar Dados Móveis
- Conecte seu computador via hotspot do celular
- IP será completamente diferente

#### Opção C - VPN/Proxy (melhor opção)
- Use uma VPN confiável
- Configure proxy no .env (veja abaixo)

### 3. **Configure o Modo Não-Headless** 🖥️

Crie arquivo `.env` na raiz do projeto:

```bash
# COPIE E COLE ISTO NO ARQUIVO .env

# MODO NÃO-HEADLESS = NAVEGADOR VISÍVEL (muito mais difícil de detectar)
HEADLESS=false

# DELAYS AUMENTADOS (5-10 segundos entre páginas)
MIN_PAGE_DELAY=5000
MAX_PAGE_DELAY=10000

# Timeout maior
NAVIGATION_TIMEOUT=60000

# Máximo de páginas
MAX_PAGES=50

# PROXY (OPCIONAL mas RECOMENDADO)
# Descomente e configure se tiver um proxy
# PROXY_URL=http://usuario:senha@ip:porta
# ou para SOCKS5:
# PROXY_URL=socks5://ip:porta
```

### 4. **Limpe os Cookies** 🍪

```bash
# Na raiz do projeto
rm -f .cookies.json
```

## 🛠️ Como Rodar Após Aguardar

### Passo 1: Aguarde 1-2 horas
Sério. O Google tem rate limiting temporal.

### Passo 2: Troque o IP
Use uma das opções acima.

### Passo 3: Configure .env
```bash
# Crie o arquivo .env
touch .env

# Adicione estas linhas:
echo "HEADLESS=false" >> .env
echo "MIN_PAGE_DELAY=5000" >> .env
echo "MAX_PAGE_DELAY=10000" >> .env
```

### Passo 4: Reinicie o servidor
```bash
npm start
```

### Passo 5: Teste com POUCOS contatos
```javascript
// No frontend, peça apenas 10-20 contatos primeiro
{
  nicho: 'dentista',
  regiao: 'são paulo',
  quantidade: 10  // ← COMECE PEQUENO!
}
```

## 🔧 Configuração de Proxy (RECOMENDADO)

### Proxies Gratuitos (para teste)
⚠️ **Cuidado**: Proxies gratuitos são lentos e pouco confiáveis.

Sites de proxies gratuitos:
- https://www.proxyscrape.com/free-proxy-list
- https://free-proxy-list.net

### Proxies Pagos (melhor opção)

**Serviços recomendados**:
1. **Webshare** - https://www.webshare.io (10 proxies grátis)
2. **Smartproxy** - https://smartproxy.com
3. **Bright Data** - https://brightdata.com

**Como configurar**:

```bash
# No arquivo .env
PROXY_URL=http://usuario:senha@proxy.exemplo.com:8080

# Ou SOCKS5
PROXY_URL=socks5://proxy.exemplo.com:1080
```

**Exemplo real (Webshare)**:
```bash
PROXY_URL=http://usuario-xxxxx:senha-xxxxx@p.webshare.io:80
```

## 📊 Proxies Rotativos (Avançado)

Para evitar detecção permanente, use proxies rotativos:

```javascript
// Em services/scraper.js, você pode modificar para usar lista de proxies
const PROXIES = [
  'http://proxy1.com:8080',
  'http://proxy2.com:8080',
  'http://proxy3.com:8080',
];

// Seleciona aleatório
const proxyUrl = PROXIES[Math.floor(Math.random() * PROXIES.length)];
```

## 🎯 Melhores Práticas APÓS Resolver RECAPTCHA

### 1. Quantidade Moderada
```
✅ BOM: 10-30 contatos por execução
⚠️ CUIDADO: 50-100 contatos
❌ EVITE: 100+ contatos
```

### 2. Intervalo Entre Buscas
```
✅ BOM: 30-60 minutos entre buscas
⚠️ CUIDADO: 15-30 minutos
❌ EVITE: < 15 minutos
```

### 3. Varie as Buscas
```javascript
// ❌ MAU - mesma busca repetida
{ nicho: 'dentista', regiao: 'são paulo' }
{ nicho: 'dentista', regiao: 'são paulo' }
{ nicho: 'dentista', regiao: 'são paulo' }

// ✅ BOM - busca variada
{ nicho: 'dentista', regiao: 'são paulo' }
{ nicho: 'restaurante', regiao: 'rio de janeiro' }
{ nicho: 'advogado', regiao: 'belo horizonte' }
```

### 4. Horários Comerciais
Use o sistema em horários normais de trabalho (9h-18h):
- Pareçe mais humano
- Menos suspeito

## 🚀 Novo Sistema Anti-RECAPTCHA

O código foi atualizado com:

### ✅ Detecção Automática
O sistema agora **detecta RECAPTCHA automaticamente** e:
- Para a execução
- Salva screenshot (`recaptcha-detected.png`)
- Mostra instruções

### ✅ Cookies Persistentes
- Salva cookies em `.cookies.json`
- Reutiliza sessão (parece usuário voltando)

### ✅ Delays Aumentados
- **Antes**: 3-6s entre páginas
- **Agora**: 5-10s entre páginas (padrão)
- Configurável via .env

### ✅ Comportamento Mais Humano
- Múltiplos movimentos de mouse (2-4 por página)
- Scroll com volta (como humano faz)
- Cliques aleatórios (30% de chance)
- Estabelece sessão no google.com.br antes

### ✅ Modo Não-Headless Disponível
```bash
# No .env
HEADLESS=false  # ← Navegador visível
```

**Por que modo visível é melhor?**
- Navegadores headless têm fingerprinting diferente
- Google detecta facilmente headless
- Navegador visível = muito mais difícil de detectar

## 🔍 Verificando se Funcionou

Após seguir os passos:

1. **Rode o programa**
2. **Observe os logs**:

```bash
✓ Cookies carregados              # ← Bom sinal
🌐 Modo: Navegador Visível         # ← Melhor ainda!
🌐 Estabelecendo sessão...         # ← Nova feature
📄 Acessando página 1/50           # ← Funcionando
   ✓ Encontrados: 8 estabelecimentos  # ← Sucesso!
```

3. **Se ver**:
```bash
🚨 RECAPTCHA DETECTADO!            # ← Ainda bloqueado
```

Significa que precisa aguardar mais tempo ou trocar IP novamente.

## 📞 Serviços de Proxy Recomendados

### Gratuitos (limitados)
1. **Webshare** - 10 proxies grátis
   - https://www.webshare.io
   - Boa velocidade
   - Fácil configuração

### Pagos (profissionais)
1. **Smartproxy** - $7/GB
   - Proxies residenciais
   - Muito difícil de detectar
   - Rotação automática

2. **Bright Data** - A partir de $500/mês
   - Melhor do mercado
   - Proxies premium
   - Para uso profissional

3. **Oxylabs** - A partir de $300/mês
   - Proxies residenciais
   - Alta confiabilidade

## ⚠️ Avisos Importantes

### Se AINDA Assim Aparecer RECAPTCHA

1. **Seu IP está na lista negra temporária**
   - Aguarde 24 horas
   - Use proxy OBRIGATORIAMENTE

2. **Google mudou a detecção**
   - Abra issue no GitHub
   - Reporte o problema

3. **Última opção: Captcha Solver**
   - Use serviços como 2Captcha
   - Anti-Captcha
   - (Requer integração adicional)

## 🎓 Resumo Rápido

```bash
# 1. AGUARDE 1-2 HORAS
# 2. TROQUE O IP (reinicie roteador ou use proxy)
# 3. CRIE .env:

cat > .env << 'EOF'
HEADLESS=false
MIN_PAGE_DELAY=5000
MAX_PAGE_DELAY=10000
NAVIGATION_TIMEOUT=60000
EOF

# 4. LIMPE COOKIES
rm -f .cookies.json

# 5. REINICIE
npm start

# 6. TESTE COM 10 CONTATOS
```

## 📚 Documentação Adicional

- **ANTI_DETECTION.md** - Técnicas anti-detecção detalhadas
- **README.md** - Informações gerais do projeto
- **.env.example** - Todas as configurações disponíveis

---

**Desenvolvido em**: Novembro 2025
**Status**: Otimizado para evitar RECAPTCHA
**Suporte**: Abra uma issue no GitHub se precisar de ajuda
