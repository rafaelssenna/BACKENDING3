const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const BlockResourcesPlugin = require('puppeteer-extra-plugin-block-resources');
const UserAgent = require('user-agents');
const fs = require('fs');
const path = require('path');

// Adiciona plugin de stealth para evitar detecção
puppeteer.use(StealthPlugin());

// Bloqueia recursos desnecessários para melhor performance
puppeteer.use(
  BlockResourcesPlugin({
    blockedTypes: new Set(['image', 'font', 'media']),
  })
);

// Configurações OTIMIZADAS (rápido mas seguro)
const CONFIG = {
  headless: process.env.HEADLESS !== 'false', // false = navegador visível
  minPageDelay: parseInt(process.env.MIN_PAGE_DELAY) || 2000, // Reduzido: 2-4s
  maxPageDelay: parseInt(process.env.MAX_PAGE_DELAY) || 4000,
  navigationTimeout: parseInt(process.env.NAVIGATION_TIMEOUT) || 45000,
  maxPages: parseInt(process.env.MAX_PAGES) || 50,
  proxyUrl: process.env.PROXY_URL || null,
  cookiesPath: path.join(__dirname, '../.cookies.json'),
};

// Sistema de delays adaptativos (acelera se estiver indo bem)
class AdaptiveDelayManager {
  constructor() {
    this.successfulPages = 0;
    this.consecutiveEmptyPages = 0;
    this.baseMinDelay = CONFIG.minPageDelay;
    this.baseMaxDelay = CONFIG.maxPageDelay;
  }

  // Calcula delay baseado no histórico
  getDelay() {
    let minDelay = this.baseMinDelay;
    let maxDelay = this.baseMaxDelay;

    // Primeiras 2 páginas: mais cauteloso
    if (this.successfulPages < 2) {
      minDelay = 3000;
      maxDelay = 5000;
    }
    // Páginas 3-5: moderado
    else if (this.successfulPages < 5) {
      minDelay = 2500;
      maxDelay = 4000;
    }
    // Depois de 5 páginas bem-sucedidas: pode acelerar
    else if (this.successfulPages >= 5) {
      minDelay = 2000;
      maxDelay = 3500;
    }

    // Se muitas páginas vazias seguidas: desacelera
    if (this.consecutiveEmptyPages >= 2) {
      minDelay += 1000;
      maxDelay += 2000;
    }

    return Math.floor(Math.random() * (maxDelay - minDelay + 1)) + minDelay;
  }

  recordSuccess() {
    this.successfulPages++;
    this.consecutiveEmptyPages = 0;
  }

  recordEmpty() {
    this.consecutiveEmptyPages++;
  }
}

// Função para delay aleatório
const randomDelay = (min = 1000, max = 3000) => {
  const delay = Math.floor(Math.random() * (max - min + 1)) + min;
  return new Promise(resolve => setTimeout(resolve, delay));
};

// Salva cookies para reutilizar sessão
async function saveCookies(page) {
  try {
    const cookies = await page.cookies();
    fs.writeFileSync(CONFIG.cookiesPath, JSON.stringify(cookies, null, 2));
    console.log('✓ Cookies salvos');
  } catch (error) {
    console.log('⚠️ Erro ao salvar cookies:', error.message);
  }
}

// Carrega cookies salvos
async function loadCookies(page) {
  try {
    if (fs.existsSync(CONFIG.cookiesPath)) {
      const cookies = JSON.parse(fs.readFileSync(CONFIG.cookiesPath, 'utf8'));
      await page.setCookie(...cookies);
      console.log('✓ Cookies carregados (sessão reutilizada)');
      return true;
    }
  } catch (error) {
    console.log('⚠️ Erro ao carregar cookies:', error.message);
  }
  return false;
}

// Detecta se há RECAPTCHA na página
async function detectRecaptcha(page) {
  try {
    const hasRecaptcha = await page.evaluate(() => {
      const recaptchaDiv = document.querySelector('iframe[src*="recaptcha"]');
      const recaptchaText = document.body.innerText.toLowerCase();

      return !!(
        recaptchaDiv ||
        recaptchaText.includes('recaptcha') ||
        recaptchaText.includes('captcha') ||
        recaptchaText.includes('unusual traffic') ||
        recaptchaText.includes('tráfego incomum')
      );
    });

    return hasRecaptcha;
  } catch (error) {
    return false;
  }
}

// Movimento de mouse OTIMIZADO (mais rápido)
async function humanMouseMovement(page) {
  try {
    const width = await page.evaluate(() => window.innerWidth);
    const height = await page.evaluate(() => window.innerHeight);

    // 1-2 movimentos (reduzido de 2-4)
    const numMovements = Math.random() > 0.5 ? 2 : 1;

    for (let i = 0; i < numMovements; i++) {
      const x = Math.floor(Math.random() * width);
      const y = Math.floor(Math.random() * height);

      await page.mouse.move(x, y, { steps: Math.floor(Math.random() * 10) + 5 });
      if (i < numMovements - 1) {
        await randomDelay(100, 300); // Reduzido de 200-800
      }
    }
  } catch (error) {
    // Ignora erros
  }
}

// Scroll OTIMIZADO (mais rápido)
async function humanScroll(page) {
  try {
    await page.evaluate(async () => {
      await new Promise((resolve) => {
        let totalHeight = 0;
        const distance = Math.floor(Math.random() * 200) + 150; // Maior distância por vez
        const maxScroll = Math.random() * document.body.scrollHeight * 0.5; // Menos scroll

        const timer = setInterval(() => {
          window.scrollBy(0, distance);
          totalHeight += distance;

          if (totalHeight >= maxScroll) {
            // Scroll rápido de volta
            window.scrollBy(0, -Math.floor(Math.random() * 200) - 100);
            clearInterval(timer);
            resolve();
          }
        }, Math.floor(Math.random() * 80) + 50); // Mais rápido: 50-130ms
      });
    });
  } catch (error) {
    // Ignora erros
  }
}

// Viewports realistas
const viewports = [
  { width: 1920, height: 1080 },
  { width: 1366, height: 768 },
  { width: 1536, height: 864 },
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
];

// Função principal de extração
async function extractLeadsRealtime(nicho, regiao, quantidade, onNewLead, onProgress) {
  let browser;
  const delayManager = new AdaptiveDelayManager();

  try {
    onProgress({ status: 'Iniciando navegador...', percent: 5 });

    // Gera user agent realista
    const userAgent = new UserAgent();
    const viewport = viewports[Math.floor(Math.random() * viewports.length)];

    const launchOptions = {
      headless: CONFIG.headless,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-blink-features=AutomationControlled',
        '--disable-features=IsolateOrigins,site-per-process',
        '--disable-web-security',
        '--disable-dev-shm-usage',
        '--disable-accelerated-2d-canvas',
        '--no-first-run',
        '--no-zygote',
        '--disable-gpu',
        '--lang=pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
        '--disable-background-timer-throttling',
        '--disable-backgrounding-occluded-windows',
        '--disable-renderer-backgrounding',
      ],
    };

    // Adiciona proxy se configurado
    if (CONFIG.proxyUrl) {
      launchOptions.args.push(`--proxy-server=${CONFIG.proxyUrl}`);
      console.log(`🔄 Usando proxy: ${CONFIG.proxyUrl}`);
    }

    console.log(`🌐 Modo: ${CONFIG.headless ? 'Headless' : 'Navegador Visível'}`);
    console.log(`⚡ Delays adaptativos: 2-5s (acelera se seguro)`);

    browser = await puppeteer.launch(launchOptions);
    const page = await browser.newPage();

    // Carrega cookies da sessão anterior
    const hasOldSession = await loadCookies(page);

    // Configura viewport aleatório
    await page.setViewport(viewport);

    // Define user agent realista
    await page.setUserAgent(userAgent.toString());

    // Headers adicionais
    await page.setExtraHTTPHeaders({
      'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
      'Accept-Encoding': 'gzip, deflate, br',
      'Upgrade-Insecure-Requests': '1',
      'Cache-Control': 'max-age=0',
      'DNT': '1',
      'Connection': 'keep-alive',
    });

    // Remove indicadores de automação
    await page.evaluateOnNewDocument(() => {
      Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
      });

      Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
      });

      Object.defineProperty(navigator, 'languages', {
        get: () => ['pt-BR', 'pt', 'en-US', 'en'],
      });

      window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {},
      };

      const originalQuery = window.navigator.permissions.query;
      window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
          Promise.resolve({ state: Notification.permission }) :
          originalQuery(parameters)
      );

      Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 8,
      });

      Object.defineProperty(navigator, 'deviceMemory', {
        get: () => 8,
      });
    });

    const query = `${nicho} ${regiao}`;
    const uniqueEstabelecimentos = new Map();
    let currentPageNum = 0;
    let paginasVaziasSeguidas = 0;

    onProgress({ status: 'Configurado! Iniciando busca...', percent: 10 });

    // Se não tem sessão antiga, estabelece uma rapidamente
    if (!hasOldSession) {
      console.log('🌐 Estabelecendo sessão rápida...');
      await page.goto('https://www.google.com.br', {
        waitUntil: 'domcontentloaded', // Mais rápido que networkidle2
        timeout: CONFIG.navigationTimeout
      });
      await randomDelay(1000, 2000); // Rápido
      await humanMouseMovement(page);
    }

    while (uniqueEstabelecimentos.size < quantidade && currentPageNum < CONFIG.maxPages) {
      const start = currentPageNum * 10;
      const url = `https://www.google.com/search?tbm=lcl&hl=pt-BR&gl=BR&q=${encodeURIComponent(query)}&start=${start}`;

      console.log(`\n📄 Página ${currentPageNum + 1}/${CONFIG.maxPages}`);
      onProgress({
        status: `Buscando página ${currentPageNum + 1}...`,
        percent: 10 + Math.floor((currentPageNum / CONFIG.maxPages) * 20)
      });

      // Navega (networkidle2 garante carregamento completo)
      await page.goto(url, {
        waitUntil: 'networkidle2',
        timeout: CONFIG.navigationTimeout
      });

      // VERIFICA RECAPTCHA
      const hasRecaptcha = await detectRecaptcha(page);

      if (hasRecaptcha) {
        console.error('🚨 RECAPTCHA DETECTADO!');

        try {
          await page.screenshot({ path: 'recaptcha-detected.png' });
          console.log('📸 Screenshot salvo: recaptcha-detected.png');
        } catch (e) {}

        throw new Error('❌ RECAPTCHA detectado!\n\n' +
          '📋 SOLUÇÕES:\n' +
          '1. ⏰ Aguarde 1-2 horas\n' +
          '2. 🔄 Troque seu IP (reinicie roteador)\n' +
          '3. 🌐 Use proxy (configure PROXY_URL no .env)\n' +
          '4. 🖥️ Configure HEADLESS=false no .env\n' +
          '5. 📉 Peça menos contatos (10-20)\n\n' +
          '📖 Veja: SOLUCAO_RECAPTCHA.md');
      }

      // Delay pós-carregamento REDUZIDO
      await randomDelay(1500, 2500);

      // Comportamento humano OTIMIZADO
      await humanMouseMovement(page);
      await randomDelay(300, 600);
      await humanScroll(page);
      await randomDelay(500, 1000);

      // Extrai estabelecimentos
      const estabelecimentosDaPagina = await page.evaluate(() => {
        const results = [];
        const seen = new Set();
        const cards = document.querySelectorAll('div[jscontroller]');

        cards.forEach(card => {
          const text = card.textContent || '';

          const headings = card.querySelectorAll('div[role="heading"]');
          let nome = '';
          if (headings.length > 0) {
            nome = headings[0].textContent.trim();
          }

          if (!nome || nome.length < 3 || nome.length > 150) return;

          if (/^(Ver mais|Pesquisar|Filtrar|Mapa|Lista|Anterior|Próxim|Direções|Salvar|Escolha)/i.test(nome)) {
            return;
          }

          const phonePatterns = [
            /\(\d{2}\)\s?\d{4,5}[-\s]?\d{4}/g,
            /\d{2}\s?\d{4,5}[-\s]?\d{4}/g,
            /\+55\s?\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4}/g,
            /\(\d{2}\)\s?\d{8,9}/g,
            /\d{10,11}/g
          ];

          let telefone = null;
          for (const pattern of phonePatterns) {
            const matches = text.match(pattern);
            if (matches && matches.length > 0) {
              telefone = matches[0];
              break;
            }
          }

          if (telefone) {
            const key = `${nome}|${telefone}`;
            if (!seen.has(key)) {
              seen.add(key);
              results.push({ nome, telefone });
            }
          }
        });

        return results;
      });

      console.log(`   ✓ Encontrados: ${estabelecimentosDaPagina.length} estabelecimentos`);

      if (estabelecimentosDaPagina.length === 0) {
        paginasVaziasSeguidas++;
        delayManager.recordEmpty();

        if (paginasVaziasSeguidas >= 5) {
          console.log('⚠️ Encerrando - 5 páginas vazias seguidas');
          break;
        }
      } else {
        paginasVaziasSeguidas = 0;
        delayManager.recordSuccess();

        let novosAdicionados = 0;
        estabelecimentosDaPagina.forEach(est => {
          const key = `${est.nome}|${est.telefone}`;
          if (!uniqueEstabelecimentos.has(key)) {
            uniqueEstabelecimentos.set(key, est);
            novosAdicionados++;
          }
        });

        console.log(`   ➕ Novos únicos: ${novosAdicionados}`);
        console.log(`   📊 Total: ${uniqueEstabelecimentos.size}/${quantidade}`);
      }

      currentPageNum++;

      if (uniqueEstabelecimentos.size >= quantidade) {
        console.log(`✅ Meta atingida: ${uniqueEstabelecimentos.size} >= ${quantidade}`);
        break;
      }

      // Delay adaptativo entre páginas
      const pageDelay = delayManager.getDelay();
      console.log(`   ⏳ Aguardando ${(pageDelay / 1000).toFixed(1)}s...`);
      await randomDelay(pageDelay, pageDelay + 500);
    }

    // Salva cookies
    await saveCookies(page);

    const unique = Array.from(uniqueEstabelecimentos.values());
    console.log(`\n✅ Total: ${unique.length} estabelecimentos (${currentPageNum} páginas)`);

    if (unique.length === 0) {
      throw new Error('Nenhum resultado encontrado. Tente outro nicho/região.');
    }

    if (unique.length < quantidade) {
      onProgress({
        status: `Encontrados ${unique.length} de ${quantidade} solicitados.`,
        percent: 35
      });
      console.log(`⚠️ Encontrado: ${unique.length}/${quantidade}`);
      await randomDelay(1000, 1500);
    }

    onProgress({ status: 'Enviando contatos...', percent: 40 });

    const limit = Math.min(unique.length, quantidade);

    for (let i = 0; i < limit; i++) {
      const est = unique[i];

      onProgress({
        status: `Enviando ${i + 1}/${limit}...`,
        percent: 40 + Math.floor((i / limit) * 55)
      });

      onNewLead({
        nome: est.nome,
        telefone: est.telefone,
        endereco: 'Não disponível',
        index: i + 1
      });

      console.log(`   ✓ [${i + 1}/${limit}] ${est.nome} - ${est.telefone}`);
      await randomDelay(15, 40);
    }

    onProgress({ status: 'Concluído!', percent: 100 });
    console.log(`\n🎉 Enviado: ${limit} contatos`);

  } catch (error) {
    console.error('❌ Erro:', error.message);
    throw error;
  } finally {
    if (browser) {
      await randomDelay(500, 1000);
      await browser.close();
    }
  }
}

module.exports = { extractLeadsRealtime };
