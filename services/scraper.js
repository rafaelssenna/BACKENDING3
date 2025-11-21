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

// Configurações (podem ser sobrescritas por variáveis de ambiente)
const CONFIG = {
  headless: process.env.HEADLESS !== 'false', // false = navegador visível (MUITO mais difícil de detectar)
  minPageDelay: parseInt(process.env.MIN_PAGE_DELAY) || 5000, // Aumentado para 5-10s
  maxPageDelay: parseInt(process.env.MAX_PAGE_DELAY) || 10000,
  navigationTimeout: parseInt(process.env.NAVIGATION_TIMEOUT) || 60000,
  maxPages: parseInt(process.env.MAX_PAGES) || 50,
  proxyUrl: process.env.PROXY_URL || null,
  cookiesPath: path.join(__dirname, '../.cookies.json'),
};

// Função para delay aleatório (simula comportamento humano)
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
      console.log('✓ Cookies carregados');
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
      // Verifica vários indicadores de RECAPTCHA
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

// Função para simular movimento de mouse humano - MELHORADO
async function humanMouseMovement(page) {
  try {
    const width = await page.evaluate(() => window.innerWidth);
    const height = await page.evaluate(() => window.innerHeight);

    // Faz vários movimentos de mouse, não apenas um
    const numMovements = Math.floor(Math.random() * 3) + 2; // 2-4 movimentos

    for (let i = 0; i < numMovements; i++) {
      const x = Math.floor(Math.random() * width);
      const y = Math.floor(Math.random() * height);

      await page.mouse.move(x, y, { steps: Math.floor(Math.random() * 20) + 10 });
      await randomDelay(200, 800);
    }
  } catch (error) {
    console.log('⚠️ Erro no movimento de mouse:', error.message);
  }
}

// Função para scroll humano - MELHORADO
async function humanScroll(page) {
  try {
    await page.evaluate(async () => {
      await new Promise((resolve) => {
        let totalHeight = 0;
        const distance = Math.floor(Math.random() * 150) + 100; // 100-250px por vez
        const maxScroll = Math.random() * document.body.scrollHeight * 0.7; // Scroll até 70% da página

        const timer = setInterval(() => {
          window.scrollBy(0, distance);
          totalHeight += distance;

          if (totalHeight >= maxScroll) {
            // Scroll de volta para cima um pouco (comportamento humano)
            window.scrollBy(0, -Math.floor(Math.random() * 300) - 100);
            clearInterval(timer);
            resolve();
          }
        }, Math.floor(Math.random() * 150) + 100); // 100-250ms entre scrolls
      });
    });
  } catch (error) {
    console.log('⚠️ Erro no scroll:', error.message);
  }
}

// Cliques aleatórios na página (NÃO em links, só para parecer humano)
async function randomClicks(page) {
  try {
    const numClicks = Math.random() > 0.7 ? 1 : 0; // 30% de chance de clicar

    for (let i = 0; i < numClicks; i++) {
      const width = await page.evaluate(() => window.innerWidth);
      const height = await page.evaluate(() => window.innerHeight);

      const x = Math.floor(Math.random() * width * 0.8); // Evita bordas
      const y = Math.floor(Math.random() * height * 0.5); // Clica na parte superior

      await page.mouse.click(x, y, { delay: Math.floor(Math.random() * 100) + 50 });
      await randomDelay(500, 1500);
    }
  } catch (error) {
    // Ignorar erros de clique
  }
}

// Viewports realistas (resoluções comuns)
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

    browser = await puppeteer.launch(launchOptions);

    const page = await browser.newPage();

    // Carrega cookies da sessão anterior (se houver)
    await loadCookies(page);

    // Configura viewport aleatório
    await page.setViewport(viewport);

    // Define user agent realista
    await page.setUserAgent(userAgent.toString());

    // Headers adicionais para parecer mais humano
    await page.setExtraHTTPHeaders({
      'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
      'Accept-Encoding': 'gzip, deflate, br',
      'Upgrade-Insecure-Requests': '1',
      'Cache-Control': 'max-age=0',
      'DNT': '1',
      'Connection': 'keep-alive',
    });

    // Remove indicadores de automação - MELHORADO
    await page.evaluateOnNewDocument(() => {
      // Sobrescreve webdriver
      Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
      });

      // Sobrescreve plugins
      Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
      });

      // Sobrescreve languages
      Object.defineProperty(navigator, 'languages', {
        get: () => ['pt-BR', 'pt', 'en-US', 'en'],
      });

      // Chrome específico
      window.chrome = {
        runtime: {},
        loadTimes: function() {},
        csi: function() {},
        app: {},
      };

      // Permissions
      const originalQuery = window.navigator.permissions.query;
      window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
          Promise.resolve({ state: Notification.permission }) :
          originalQuery(parameters)
      );

      // Hardware concurrency
      Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 8,
      });

      // Device memory
      Object.defineProperty(navigator, 'deviceMemory', {
        get: () => 8,
      });
    });

    const query = `${nicho} ${regiao}`;
    const uniqueEstabelecimentos = new Map();
    let currentPageNum = 0;
    let paginasVaziasSeguidas = 0;

    onProgress({ status: 'Configurado! Iniciando busca...', percent: 10 });

    // Primeiro acesso ao Google (estabelece sessão)
    console.log('🌐 Estabelecendo sessão com Google...');
    await page.goto('https://www.google.com.br', {
      waitUntil: 'networkidle2',
      timeout: CONFIG.navigationTimeout
    });

    await randomDelay(2000, 4000);
    await humanMouseMovement(page);
    await randomDelay(1000, 2000);

    while (uniqueEstabelecimentos.size < quantidade && currentPageNum < CONFIG.maxPages) {
      const start = currentPageNum * 10;
      const url = `https://www.google.com/search?tbm=lcl&hl=pt-BR&gl=BR&q=${encodeURIComponent(query)}&start=${start}`;

      console.log(`\n📄 Acessando página ${currentPageNum + 1}/${CONFIG.maxPages}`);
      onProgress({
        status: `Buscando página ${currentPageNum + 1}...`,
        percent: 10 + Math.floor((currentPageNum / CONFIG.maxPages) * 20)
      });

      // Navega com timeout maior
      await page.goto(url, {
        waitUntil: 'networkidle2',
        timeout: CONFIG.navigationTimeout
      });

      // VERIFICA SE TEM RECAPTCHA
      const hasRecaptcha = await detectRecaptcha(page);

      if (hasRecaptcha) {
        console.error('🚨 RECAPTCHA DETECTADO!');

        // Salva screenshot para debug
        try {
          await page.screenshot({ path: 'recaptcha-detected.png' });
          console.log('📸 Screenshot salvo: recaptcha-detected.png');
        } catch (e) {}

        throw new Error('RECAPTCHA detectado! Recomendações:\n' +
          '1. Aguarde 1-2 horas antes de tentar novamente\n' +
          '2. Troque seu IP (reinicie o roteador)\n' +
          '3. Use um proxy (configure PROXY_URL no .env)\n' +
          '4. Reduza a quantidade de contatos\n' +
          '5. Configure HEADLESS=false no .env para usar navegador visível');
      }

      // Delay aleatório após carregar - AUMENTADO
      await randomDelay(3000, 5000);

      // Simula comportamento humano - MELHORADO
      await humanMouseMovement(page);
      await randomDelay(800, 1500);
      await humanScroll(page);
      await randomDelay(1000, 2000);
      await randomClicks(page);
      await randomDelay(500, 1000);

      // Extrai estabelecimentos da página atual
      const estabelecimentosDaPagina = await page.evaluate(() => {
        const results = [];
        const seen = new Set();

        // Pega TODOS os divs com jscontroller
        const cards = document.querySelectorAll('div[jscontroller]');

        cards.forEach(card => {
          const text = card.textContent || '';

          // Busca nome
          const headings = card.querySelectorAll('div[role="heading"]');
          let nome = '';
          if (headings.length > 0) {
            nome = headings[0].textContent.trim();
          }

          // Se não tem nome, pula
          if (!nome || nome.length < 3 || nome.length > 150) return;

          // Filtra lixo
          if (/^(Ver mais|Pesquisar|Filtrar|Mapa|Lista|Anterior|Próxim|Direções|Salvar|Escolha)/i.test(nome)) {
            return;
          }

          // Busca telefone com TODAS as variações
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

          // Só adiciona se tem telefone
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
        if (paginasVaziasSeguidas >= 5) {
          console.log('⚠️ Encerrando busca - 5 páginas vazias seguidas');
          break;
        }
      } else {
        paginasVaziasSeguidas = 0;

        // Adiciona novos únicos
        let novosAdicionados = 0;
        estabelecimentosDaPagina.forEach(est => {
          const key = `${est.nome}|${est.telefone}`;
          if (!uniqueEstabelecimentos.has(key)) {
            uniqueEstabelecimentos.set(key, est);
            novosAdicionados++;
          }
        });

        console.log(`   ➕ Novos únicos: ${novosAdicionados}`);
        console.log(`   📊 Total único até agora: ${uniqueEstabelecimentos.size}/${quantidade}`);
      }

      currentPageNum++;

      if (uniqueEstabelecimentos.size >= quantidade) {
        console.log(`✅ Meta atingida: ${uniqueEstabelecimentos.size} >= ${quantidade}`);
        break;
      }

      const percentComplete = Math.min(100, Math.floor((uniqueEstabelecimentos.size / quantidade) * 100));

      // Delay aleatório entre páginas - MUITO IMPORTANTE E AUMENTADO!
      const pageDelay = Math.floor(Math.random() * (CONFIG.maxPageDelay - CONFIG.minPageDelay + 1)) + CONFIG.minPageDelay;
      console.log(`   ⏳ Aguardando ${(pageDelay / 1000).toFixed(1)}s antes da próxima página...`);
      await randomDelay(pageDelay, pageDelay + 1000);
    }

    // Salva cookies para próxima sessão
    await saveCookies(page);

    const unique = Array.from(uniqueEstabelecimentos.values());
    console.log(`\n✅ Total coletado: ${unique.length} estabelecimentos únicos (${currentPageNum} páginas)`);

    if (unique.length === 0) {
      throw new Error('Nenhum resultado encontrado. O Google pode ter mudado a estrutura HTML.');
    }

    if (unique.length < quantidade) {
      onProgress({
        status: `Encontrados ${unique.length} de ${quantidade} solicitados.`,
        percent: 35
      });
      console.log(`⚠️ Solicitado: ${quantidade}, Encontrado: ${unique.length}`);
      await randomDelay(1000, 2000);
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
      await randomDelay(20, 50);
    }

    onProgress({ status: 'Concluído!', percent: 100 });
    console.log(`\n🎉 Total enviado: ${limit} contatos`);

  } catch (error) {
    console.error('❌ Erro:', error.message);
    throw error;
  } finally {
    if (browser) {
      await randomDelay(1000, 2000);
      await browser.close();
    }
  }
}

module.exports = { extractLeadsRealtime };
