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

    let allEstabelecimentos = [];
    let currentPage = 0;
    const maxPages = 50; // Aumentado para garantir busca completa
    let paginasVaziasSeguidas = 0;

    // Continua buscando até ter leads suficientes
    while (allEstabelecimentos.length < quantidade && currentPage < maxPages) {
      const start = currentPage * 10; // Google usa start=0, 10, 20, 30...
      const url = `https://www.google.com/search?tbm=lcl&hl=pt-BR&gl=BR&q=${encodeURIComponent(query)}&start=${start}`;

      console.log(`Acessando página ${currentPage + 1}: ${url}`);
      onProgress({
        status: `Buscando página ${currentPage + 1}...`,
        percent: 10 + Math.floor((currentPage / maxPages) * 20)
      });

      await page.goto(url, { waitUntil: 'networkidle0', timeout: 30000 });
      await new Promise(r => setTimeout(r, 2000));

      // Extrai estabelecimentos da página atual
      const estabelecimentosDaPagina = await page.evaluate(() => {
        const results = [];

        // Tenta múltiplos seletores para garantir que pegue todos os cards
        const selectors = [
          'div[jscontroller]',
          'div[data-ved]',
          'div.VkpGBb',
          'div[jsname]'
        ];

        let allCards = new Set();
        selectors.forEach(selector => {
          const elements = document.querySelectorAll(selector);
          elements.forEach(el => allCards.add(el));
        });

        allCards.forEach(card => {
          const text = card.textContent || '';

          // Busca nome com múltiplos seletores
          const headingSelectors = [
            'div[role="heading"]',
            'h3',
            'h2',
            'div.dbg0pd',
            'span[class*="fontHeadline"]'
          ];

          let nome = '';
          for (const selector of headingSelectors) {
            const heading = card.querySelector(selector);
            if (heading && heading.textContent.trim()) {
              nome = heading.textContent.trim();
              break;
            }
          }

          // Busca telefone com regex melhorado - aceita mais formatos
          const phonePatterns = [
            /\(\d{2}\)\s?\d{4,5}-?\d{4}/g,           // (11) 98765-4321
            /\d{2}\s?\d{4,5}-?\d{4}/g,                // 11 98765-4321
            /\+55\s?\d{2}\s?\d{4,5}-?\d{4}/g,        // +55 11 98765-4321
            /\(\d{2}\)\s?\d{8,9}/g                    // (11) 987654321
          ];

          let telefone = null;
          for (const pattern of phonePatterns) {
            const match = text.match(pattern);
            if (match) {
              telefone = match[0];
              break;
            }
          }

          if (nome && telefone && nome.length > 3 && nome.length < 150) {
            results.push({
              nome: nome,
              telefone: telefone
            });
          }
        });

        return results;
      });

      console.log(`Página ${currentPage + 1}: ${estabelecimentosDaPagina.length} estabelecimentos com telefone encontrados`);

      // Controla páginas vazias seguidas
      if (estabelecimentosDaPagina.length === 0) {
        paginasVaziasSeguidas++;
        console.log(`Nenhum resultado nesta página (${paginasVaziasSeguidas} vazias seguidas)`);

        // Para se teve 5 páginas vazias seguidas
        if (paginasVaziasSeguidas >= 5) {
          console.log('Encerrando busca - 5 páginas vazias seguidas');
          break;
        }
      } else {
        paginasVaziasSeguidas = 0; // Reseta contador
        // Adiciona os novos estabelecimentos
        allEstabelecimentos = allEstabelecimentos.concat(estabelecimentosDaPagina);
        console.log(`Total acumulado: ${allEstabelecimentos.length} estabelecimentos`);
      }

      currentPage++;

      // Se já temos o suficiente, para
      if (allEstabelecimentos.length >= quantidade) {
        console.log(`✓ Quantidade atingida: ${allEstabelecimentos.length} >= ${quantidade}`);
        break;
      }

      // Log de progresso
      const percentComplete = Math.min(100, Math.floor((allEstabelecimentos.length / quantidade) * 100));
      console.log(`Progresso: ${percentComplete}% (${allEstabelecimentos.length}/${quantidade})`);
    }

    // Remove duplicatas de todas as páginas
    const unique = [];
    const seen = new Set();

    allEstabelecimentos.forEach(item => {
      const key = `${item.nome}|${item.telefone}`;
      if (!seen.has(key)) {
        seen.add(key);
        unique.push(item);
      }
    });

    console.log(`Total coletado: ${unique.length} estabelecimentos (${currentPage} páginas)`);

    if (unique.length === 0) {
      throw new Error('Nenhum resultado encontrado');
    }

    // Avisa se encontrou menos do que o solicitado
    if (unique.length < quantidade) {
      onProgress({
        status: `Encontrados apenas ${unique.length} contatos. Não há mais resultados disponíveis.`,
        percent: 35
      });
      console.log(`⚠️ Solicitado: ${quantidade}, Encontrado: ${unique.length}`);
      await new Promise(r => setTimeout(r, 2000)); // Pausa para usuário ver a mensagem
    }

    onProgress({ status: 'Extraindo contatos...', percent: 40 });

    const limit = Math.min(unique.length, quantidade);

    // Envia os resultados em tempo real
    for (let i = 0; i < limit; i++) {
      const est = unique[i];

      onProgress({
        status: `Extraindo ${i + 1}/${limit}...`,
        percent: 40 + Math.floor((i / limit) * 55)
      });

      onNewLead({
        nome: est.nome,
        telefone: est.telefone,
        endereco: 'Não disponível',
        index: i + 1
      });

      console.log(`✓ [${i + 1}] ${est.nome} - ${est.telefone}`);

      // Pequeno delay para não sobrecarregar o socket
      await new Promise(r => setTimeout(r, 50));
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
