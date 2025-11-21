# ⚡ Sistema de Velocidade Otimizada

## RÁPIDO + SEGURO = Melhor dos Dois Mundos!

O sistema agora usa **delays adaptativos** que aceleram automaticamente quando detecta que está seguro.

---

## 🎯 Velocidade por Página

### Sistema Adaptativo Inteligente

O tempo de espera entre páginas **muda automaticamente** baseado no sucesso:

| Situação | Delay | Motivo |
|----------|-------|--------|
| **Páginas 1-2** | 3-5 segundos | Cauteloso no início |
| **Páginas 3-5** | 2.5-4 segundos | Moderado |
| **Páginas 6+** | 2-3.5 segundos | ⚡ Acelerado (seguro!) |
| **Páginas vazias** | +1-2 segundos | Desacelera (pode ter problema) |

### Exemplo Prático

Buscando 50 contatos (~5 páginas):
```
Página 1: 4.2s de espera (cauteloso)
Página 2: 3.8s de espera (cauteloso)
Página 3: 3.1s de espera (moderado)
Página 4: 2.7s de espera (moderado)
Página 5: 2.3s de espera (acelerado!)

Total: ~16s de delays (antes era ~40-50s)
Tempo total: ~25-30s (3x MAIS RÁPIDO!)
```

---

## 🚀 Otimizações Implementadas

### 1. Delays Adaptativos
```javascript
class AdaptiveDelayManager {
  - Acelera após páginas bem-sucedidas
  - Desacelera se encontrar páginas vazias
  - Ajusta automaticamente em tempo real
}
```

**Benefício**: Máxima velocidade quando seguro, cautela quando necessário.

### 2. Comportamento Humano Otimizado

**Antes**:
- 2-4 movimentos de mouse
- Delays de 200-800ms entre movimentos
- Scroll completo da página

**Agora**:
- 1-2 movimentos de mouse (50% menos)
- Delays de 100-300ms (60% mais rápido)
- Scroll parcial (50% da página)

**Resultado**: ~2-3s economizados por página!

### 3. Estabelecimento de Sessão Rápido

**Antes**:
```javascript
await page.goto('google.com.br', { waitUntil: 'networkidle2' });
await delay(2000-4000);
await humanMouseMovement();
await delay(1000-2000);
```

**Agora**:
```javascript
// Só se não tiver cookies salvos
if (!hasOldSession) {
  await page.goto('google.com.br', { waitUntil: 'domcontentloaded' });
  await delay(1000-2000);
  await humanMouseMovement();
}
// Se tem cookies: pula tudo! (4-8s economizados)
```

### 4. Tempos de Espera Reduzidos

| Ação | Antes | Agora | Economia |
|------|-------|-------|----------|
| Pós-carregamento | 3-5s | 1.5-2.5s | **50%** |
| Entre mouse e scroll | 800-1500ms | 300-600ms | **60%** |
| Após scroll | 1-2s | 0.5-1s | **50%** |
| Envio de leads | 20-50ms | 15-40ms | **25%** |

---

## 📊 Comparação de Performance

### 50 Contatos (~5 páginas)

| Métrica | Versão Anterior | Versão Otimizada | Melhoria |
|---------|----------------|------------------|----------|
| Delay por página | 5-10s | 2-5s (adaptativo) | **2-3x mais rápido** |
| Comportamento humano | 5-8s | 2-4s | **2x mais rápido** |
| Estabelecimento sessão | 4-8s | 0-2s (se tem cookies) | **Até 4x** |
| **Tempo total** | **60-90s** | **20-35s** | **3x MAIS RÁPIDO** |

### 100 Contatos (~10 páginas)

| Métrica | Versão Anterior | Versão Otimizada | Melhoria |
|---------|----------------|------------------|----------|
| **Tempo total** | **120-180s** | **40-70s** | **3x MAIS RÁPIDO** |

---

## 🛡️ Segurança Mantida

### Proteções Ativas

✅ **Stealth Mode**: Puppeteer-extra com plugin stealth
✅ **User Agents Reais**: Rotação automática
✅ **Fingerprinting**: Headers completos e realistas
✅ **Detecção de RECAPTCHA**: Para imediatamente se detectar
✅ **Cookies Persistentes**: Reutiliza sessão
✅ **Comportamento Humano**: Mouse, scroll, delays aleatórios

### Como Funciona a Segurança

1. **Primeiras páginas**: Mais cauteloso (3-5s)
2. **Se OK**: Acelera progressivamente
3. **Se problema**: Desacelera automaticamente
4. **Se RECAPTCHA**: Para e alerta

**Resultado**: Rápido quando possível, cauteloso quando necessário!

---

## ⚙️ Configuração

### Padrão (Recomendado)
```bash
# Deixe em branco ou use valores padrão
# Sistema acelera automaticamente!
```

### Personalizado

Se quiser controlar manualmente:

```bash
# .env

# SUPER RÁPIDO (mais arriscado)
MIN_PAGE_DELAY=1500
MAX_PAGE_DELAY=3000

# BALANCEADO (padrão) ✅
MIN_PAGE_DELAY=2000
MAX_PAGE_DELAY=4000

# SUPER CAUTELOSO (mais lento)
MIN_PAGE_DELAY=4000
MAX_PAGE_DELAY=8000
```

---

## 🎮 Modos de Operação

### Modo Padrão (Headless)
```bash
HEADLESS=new  # ou deixe em branco
```
- ⚡ Mais rápido
- 🤖 Stealth mode ativo
- ✅ Recomendado para uso normal

### Modo Seguro (Navegador Visível)
```bash
HEADLESS=false
```
- 🛡️ Mais difícil de detectar
- 👀 Você vê o navegador
- 🚨 Use se tiver RECAPTCHA

---

## 📈 Logs de Velocidade

O sistema mostra em tempo real:

```bash
⚡ Delays adaptativos: 2-5s (acelera se seguro)

📄 Página 1/50
   ✓ Encontrados: 8 estabelecimentos
   ➕ Novos únicos: 8
   📊 Total: 8/50
   ⏳ Aguardando 4.2s...  # ← Cauteloso

📄 Página 6/50
   ✓ Encontrados: 9 estabelecimentos
   ➕ Novos únicos: 7
   📊 Total: 45/50
   ⏳ Aguardando 2.3s...  # ← Acelerou! 🚀
```

---

## 💡 Dicas de Performance

### 1. Use Cookies Persistentes
Na segunda execução, o sistema reutiliza cookies:
- **Economia**: 4-8 segundos no início
- **Automático**: Não precisa fazer nada

### 2. Peça Quantidades Razoáveis
- 10-30 contatos: **Super rápido** (10-20s)
- 50-100 contatos: **Rápido** (30-70s)
- 100+ contatos: **Moderado** (70s+)

### 3. Deixe o Sistema Acelerar
- Não interrompa a execução
- O sistema acelera automaticamente
- Quanto mais páginas, mais rápido fica!

---

## 🔍 Troubleshooting

### "Ainda está muito lento!"

**Verifique**:
1. Está usando modo headless? (`HEADLESS=new`)
2. Tem cookies salvos? (2ª execução é mais rápida)
3. Quantas páginas vazias seguidas? (Desacelera automaticamente)

**Solução**:
```bash
# Force velocidade máxima (mais arriscado)
MIN_PAGE_DELAY=1500
MAX_PAGE_DELAY=2500
```

### "Apareceu RECAPTCHA!"

O sistema acelerou demais para seu IP/região.

**Solução**:
```bash
# Use modo cauteloso
MIN_PAGE_DELAY=4000
MAX_PAGE_DELAY=6000
HEADLESS=false
```

Ou aguarde 1-2 horas e troque o IP.

---

## 📊 Estatísticas de Uso

### Cenário Ideal (sem RECAPTCHA prévio)

| Contatos | Páginas | Tempo Estimado | Velocidade |
|----------|---------|----------------|------------|
| 10 | 1-2 | 8-15s | ⚡⚡⚡ |
| 30 | 3-4 | 15-25s | ⚡⚡⚡ |
| 50 | 5-6 | 20-35s | ⚡⚡ |
| 100 | 10-12 | 40-70s | ⚡ |

### Cenário Cauteloso (após RECAPTCHA)

| Contatos | Páginas | Tempo Estimado | Velocidade |
|----------|---------|----------------|------------|
| 10 | 1-2 | 15-25s | ⚡⚡ |
| 30 | 3-4 | 30-50s | ⚡ |
| 50 | 5-6 | 45-80s | 🐢 |

---

## 🎉 Resumo

### O Que Mudou

| Aspecto | Antes | Agora |
|---------|-------|-------|
| Delays entre páginas | Fixo (5-10s) | **Adaptativo (2-5s)** |
| Velocidade | Lento | **3x mais rápido** |
| Segurança | Alta | **Mantida** |
| Inteligência | Básica | **Adaptativa** |

### Por Que é Melhor

✅ **3x mais rápido** em condições normais
✅ **Mantém segurança** com stealth mode
✅ **Acelera automaticamente** quando seguro
✅ **Desacelera automaticamente** se necessário
✅ **Detecta RECAPTCHA** e para imediatamente
✅ **Reutiliza sessões** com cookies

---

**Desenvolvido**: Novembro 2025
**Status**: ⚡ Otimizado e testado
**Performance**: 3x mais rápido que versão anterior
