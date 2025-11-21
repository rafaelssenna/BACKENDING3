const puppeteer = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const BlockResourcesPlugin = require('puppeteer-extra-plugin-block-resources');
const UserAgent = require('user-agents');

// Adiciona plugin de stealth para evitar detecção
puppeteer.use(StealthPlugin());

// Bloqueia recursos desnecessários para melhor performance
puppeteer.use(
  BlockResourcesPlugin({
    blockedTypes: new Set(['image', 'font', 'media']),
  })
);

// Função para delay aleatório (simula comportamento humano)
const randomDelay = (min = 1000, max = 3000) => {
  const delay = Math.floor(Math.random() * (max - min + 1)) + min;
  return new Promise(resolve => setTimeout(resolve, delay));
};

// Função para simular movimento de mouse humano
async function humanMouseMovement(page) {
  const width = await page.evaluate(() => window.innerWidth);
  const height = await page.evaluate(() => window.innerHeight);

  const x = Math.floor(Math.random() * width);
  const y = Math.floor(Math.random() * height);

  await page.mouse.move(x, y, { steps: 10 });
}

// Função para scroll humano
async function humanScroll(page) {
  await page.evaluate(async () => {
    await new Promise((resolve) => {
      let totalHeight = 0;
      const distance = Math.floor(Math.random() * 100) + 100; // 100-200px por vez
      const timer = setInterval(() => {
        const scrollHeight = document.body.scrollHeight;
        window.scrollBy(0, distance);
        totalHeight += distance;

        if (totalHeight >= scrollHeight / 2) {
          clearInterval(timer);
          resolve();
        }
      }, Math.floor(Math.random() * 100) + 100); // 100-200ms entre scrolls
    });
  });
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

    browser = await puppeteer.launch({
      headless: 'new',
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
      ],
    });

    const page = await browser.newPage();

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
    });

    // Remove indicadores de automação
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
      };

      // Permissions
      const originalQuery = window.navigator.permissions.query;
      window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
          Promise.resolve({ state: Notification.permission }) :
          originalQuery(parameters)
      );
    });

    const query = `${nicho} ${regiao}`;
    const uniqueEstabelecimentos = new Map();
    let currentPageNum = 0;
    const maxPages = 50;
    let paginasVaziasSeguidas = 0;

    onProgress({ status: 'Configurado! Iniciando busca...', percent: 10 });

    while (uniqueEstabelecimentos.size < quantidade && currentPageNum < maxPages) {
      const start = currentPageNum * 10;
      const url = `https://www.google.com/search?tbm=lcl&hl=pt-BR&gl=BR&q=${encodeURIComponent(query)}&start=${start}`;

      console.log(`Acessando página ${currentPageNum + 1}: ${url}`);
      onProgress({
        status: `Buscando página ${currentPageNum + 1}...`,
        percent: 10 + Math.floor((currentPageNum / maxPages) * 20)
      });

      // Navega com timeout maior
      await page.goto(url, {
        waitUntil: 'networkidle2',
        timeout: 45000
      });

      // Delay aleatório após carregar
      await randomDelay(2000, 4000);

      // Simula comportamento humano
      await humanMouseMovement(page);
      await randomDelay(500, 1500);
      await humanScroll(page);
      await randomDelay(1000, 2000);

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

      console.log(`Página ${currentPageNum + 1}: ${estabelecimentosDaPagina.length} estabelecimentos com telefone`);

      if (estabelecimentosDaPagina.length === 0) {
        paginasVaziasSeguidas++;
        if (paginasVaziasSeguidas >= 5) {
          console.log('Encerrando busca - 5 páginas vazias seguidas');
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

        console.log(`   → Novos únicos adicionados: ${novosAdicionados} de ${estabelecimentosDaPagina.length}`);
        console.log(`   → Total de únicos até agora: ${uniqueEstabelecimentos.size}`);
      }

      currentPageNum++;

      if (uniqueEstabelecimentos.size >= quantidade) {
        console.log(`✓ Quantidade de únicos atingida: ${uniqueEstabelecimentos.size} >= ${quantidade}`);
        break;
      }

      const percentComplete = Math.min(100, Math.floor((uniqueEstabelecimentos.size / quantidade) * 100));
      console.log(`Progresso: ${percentComplete}% (${uniqueEstabelecimentos.size}/${quantidade})`);

      // Delay aleatório entre páginas (importante!)
      await randomDelay(3000, 6000);
    }

    const unique = Array.from(uniqueEstabelecimentos.values());
    console.log(`Total coletado: ${unique.length} estabelecimentos únicos (${currentPageNum} páginas)`);

    if (unique.length === 0) {
      throw new Error('Nenhum resultado encontrado');
    }

    if (unique.length < quantidade) {
      onProgress({
        status: `Encontrados ${unique.length} contatos de ${quantidade} solicitados.`,
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

      console.log(`✓ [${i + 1}] ${est.nome} - ${est.telefone}`);
      await randomDelay(20, 50);
    }

    onProgress({ status: 'Concluído!', percent: 100 });
    console.log(`Total enviado: ${limit}`);

  } catch (error) {
    console.error('Erro:', error);
    throw new Error(`Erro: ${error.message}`);
  } finally {
    if (browser) {
      await randomDelay(1000, 2000);
      await browser.close();
    }
  }
}

module.exports = { extractLeadsRealtime };
