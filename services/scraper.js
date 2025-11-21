const puppeteer = require('puppeteer');

async function extractLeadsRealtime(nicho, regiao, quantidade, onNewLead, onProgress) {
  let browser;

  try {
    onProgress({ status: 'Iniciando...', percent: 5 });

    browser = await puppeteer.launch({
      headless: 'new',
      args: ['--no-sandbox', '--disable-setuid-sandbox']
    });

    const page = await browser.newPage();
    const query = `${nicho} ${regiao}`;

    const uniqueEstabelecimentos = new Map();
    let currentPageNum = 0;
    const maxPages = 50;
    let paginasVaziasSeguidas = 0;

    // Continua buscando até ter leads ÚNICOS suficientes
    while (uniqueEstabelecimentos.size < quantidade && currentPageNum < maxPages) {
      const start = currentPageNum * 10;
      const url = `https://www.google.com/search?tbm=lcl&hl=pt-BR&gl=BR&q=${encodeURIComponent(query)}&start=${start}`;

      console.log(`Acessando página ${currentPageNum + 1}: ${url}`);
      onProgress({
        status: `Buscando página ${currentPageNum + 1}...`,
        percent: 10 + Math.floor((currentPageNum / maxPages) * 20)
      });

      await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
      await new Promise(r => setTimeout(r, 1500));

      // Extrai todos os links clicáveis de estabelecimentos
      const links = await page.evaluate(() => {
        const results = [];
        const seen = new Set();

        // Busca por cards de estabelecimentos com nome
        const cards = document.querySelectorAll('div[jscontroller]');

        cards.forEach(card => {
          // Busca nome
          const headings = card.querySelectorAll('div[role="heading"]');
          if (headings.length === 0) return;

          const nome = headings[0].textContent?.trim();
          if (!nome || nome.length < 3 || nome.length > 150) return;

          // Filtra lixo
          if (/^(Ver mais|Pesquisar|Filtrar|Mapa|Lista|Anterior|Próxim|Direções|Salvar|Escolha)/i.test(nome)) {
            return;
          }

          // Busca link dentro do card
          const link = card.querySelector('a[href]');
          if (!link) return;

          const href = link.href;

          // Verifica se é um link válido do Maps
          if (href && (href.includes('maps') || href.includes('place')) && !seen.has(nome)) {
            seen.add(nome);
            results.push({ nome, href });
          }
        });

        return results;
      });

      console.log(`Página ${currentPageNum + 1}: ${links.length} estabelecimentos encontrados`);

      if (links.length === 0) {
        paginasVaziasSeguidas++;
        if (paginasVaziasSeguidas >= 5) {
          console.log('Encerrando busca - 5 páginas vazias seguidas');
          break;
        }
      } else {
        paginasVaziasSeguidas = 0;

        // Processa links em lotes pequenos para ser mais rápido
        let novosAdicionados = 0;
        for (let i = 0; i < links.length && uniqueEstabelecimentos.size < quantidade; i++) {
          const { nome, href } = links[i];

          // Verifica se já temos esse nome
          if (Array.from(uniqueEstabelecimentos.values()).some(e => e.nome === nome)) {
            continue;
          }

          try {
            // Abre em nova aba para não perder a listagem
            const detailPage = await browser.newPage();
            await detailPage.goto(href, { waitUntil: 'domcontentloaded', timeout: 10000 });
            await new Promise(r => setTimeout(r, 500));

            // Extrai telefone da página de detalhes
            const telefone = await detailPage.evaluate(() => {
              const phonePatterns = [
                /\(\d{2}\)\s?\d{4,5}[-\s]?\d{4}/g,
                /\d{2}\s?\d{4,5}[-\s]?\d{4}/g,
                /\+55\s?\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4}/g,
                /\(\d{2}\)\s?\d{8,9}/g,
                /\d{10,11}/g
              ];

              const bodyText = document.body.textContent || '';

              for (const pattern of phonePatterns) {
                const matches = bodyText.match(pattern);
                if (matches && matches.length > 0) {
                  return matches[0];
                }
              }

              return null;
            });

            await detailPage.close();

            if (telefone) {
              const key = `${nome}|${telefone}`;
              if (!uniqueEstabelecimentos.has(key)) {
                uniqueEstabelecimentos.set(key, { nome, telefone });
                novosAdicionados++;
                console.log(`   ✓ [${uniqueEstabelecimentos.size}] ${nome} - ${telefone}`);
              }
            }
          } catch (err) {
            console.log(`   ✗ Erro ao acessar ${nome}: ${err.message}`);
          }

          // Para se já temos o suficiente
          if (uniqueEstabelecimentos.size >= quantidade) {
            break;
          }
        }

        console.log(`   → Novos únicos adicionados: ${novosAdicionados}`);
        console.log(`   → Total de únicos até agora: ${uniqueEstabelecimentos.size}`);
      }

      currentPageNum++;

      if (uniqueEstabelecimentos.size >= quantidade) {
        console.log(`✓ Quantidade de únicos atingida: ${uniqueEstabelecimentos.size} >= ${quantidade}`);
        break;
      }

      const percentComplete = Math.min(100, Math.floor((uniqueEstabelecimentos.size / quantidade) * 100));
      console.log(`Progresso: ${percentComplete}% (${uniqueEstabelecimentos.size}/${quantidade})`);
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
      await new Promise(r => setTimeout(r, 2000));
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

      await new Promise(r => setTimeout(r, 30));
    }

    onProgress({ status: 'Concluído!', percent: 100 });
    console.log(`Total enviado: ${limit}`);

  } catch (error) {
    console.error('Erro:', error);
    throw new Error(`Erro: ${error.message}`);
  } finally {
    if (browser) await browser.close();
  }
}

module.exports = { extractLeadsRealtime };
