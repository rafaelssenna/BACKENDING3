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
    const maxPages = 10; // Máximo de páginas para evitar loop infinito

    // Continua buscando até ter leads suficientes ou atingir o máximo de páginas
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
        const cards = document.querySelectorAll('div[jscontroller]');

        cards.forEach(card => {
          const text = card.textContent || '';

          // Busca nome
          const headings = card.querySelectorAll('div[role="heading"]');
          let nome = '';
          if (headings.length > 0) {
            nome = headings[0].textContent.trim();
          }

          // Busca telefone
          const phoneMatch = text.match(/\(\d{2}\)\s?\d{4,5}-?\d{4}/);

          if (nome && phoneMatch && nome.length > 3 && nome.length < 100) {
            results.push({
              nome: nome,
              telefone: phoneMatch[0]
            });
          }
        });

        return results;
      });

      console.log(`Página ${currentPage + 1}: ${estabelecimentosDaPagina.length} estabelecimentos encontrados`);

      // Se não encontrou nada, para de buscar
      if (estabelecimentosDaPagina.length === 0) {
        console.log('Nenhum resultado encontrado nesta página, encerrando busca');
        break;
      }

      // Adiciona os novos estabelecimentos
      allEstabelecimentos = allEstabelecimentos.concat(estabelecimentosDaPagina);
      currentPage++;

      // Se já temos o suficiente, para
      if (allEstabelecimentos.length >= quantidade) {
        break;
      }
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
