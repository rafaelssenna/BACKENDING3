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

    const uniqueEstabelecimentos = new Map(); // Armazena únicos por chave nome|telefone
    let currentPage = 0;
    const maxPages = 50; // Aumentado para garantir busca completa
    let paginasVaziasSeguidas = 0;
    let paginasSemNovos = 0; // Conta páginas que não trouxeram nenhum novo único

    // Continua buscando até ter leads ÚNICOS suficientes
    while (uniqueEstabelecimentos.size < quantidade && currentPage < maxPages) {
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
        const seen = new Set(); // Remove duplicatas DENTRO da mesma página

        // Seletor específico para cards de estabelecimentos
        const cards = document.querySelectorAll('div[jscontroller]');

        cards.forEach(card => {
          const text = card.textContent || '';

          // Busca nome - usa div[role="heading"] que é o mais confiável
          const headings = card.querySelectorAll('div[role="heading"]');
          let nome = '';
          if (headings.length > 0) {
            nome = headings[0].textContent.trim();
          }

          // Busca telefone com TODOS os padrões possíveis
          const phonePatterns = [
            /\(\d{2}\)\s?\d{4,5}[-\s]?\d{4}/g,       // (11) 98765-4321 ou (11) 98765 4321
            /\d{2}\s?\d{4,5}[-\s]?\d{4}/g,           // 11 98765-4321 ou 11 98765 4321
            /\+55\s?\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4}/g, // +55 (11) 98765-4321
            /\(\d{2}\)\s?\d{8,9}/g,                   // (11) 987654321
            /\d{10,11}/g                              // 11987654321
          ];

          let telefone = null;
          for (const pattern of phonePatterns) {
            const matches = text.match(pattern);
            if (matches && matches.length > 0) {
              // Pega o primeiro match válido
              telefone = matches[0];
              break;
            }
          }

          // Valida se é realmente um estabelecimento
          if (nome && telefone && nome.length > 3 && nome.length < 150) {
            // Verifica se não é lixo (menus, botões, etc)
            const temPalavrasInvalidas = /^(Ver mais|Pesquisar|Filtrar|Mapa|Lista|Anterior|Próxim)/i.test(nome);

            if (!temPalavrasInvalidas) {
              // Verifica duplicata na mesma página
              const key = `${nome}|${telefone}`;
              if (!seen.has(key)) {
                seen.add(key);
                results.push({
                  nome: nome,
                  telefone: telefone
                });
              }
            }
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

        // Adiciona apenas os NOVOS únicos ao Map
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

        // Conta páginas sem novos
        if (novosAdicionados === 0) {
          paginasSemNovos++;
          if (paginasSemNovos >= 3) {
            console.log('Encerrando busca - 3 páginas seguidas sem novos únicos');
            break;
          }
        } else {
          paginasSemNovos = 0;
        }
      }

      currentPage++;

      // Se já temos únicos suficientes, para
      if (uniqueEstabelecimentos.size >= quantidade) {
        console.log(`✓ Quantidade de únicos atingida: ${uniqueEstabelecimentos.size} >= ${quantidade}`);
        break;
      }

      // Log de progresso baseado em únicos
      const percentComplete = Math.min(100, Math.floor((uniqueEstabelecimentos.size / quantidade) * 100));
      console.log(`Progresso: ${percentComplete}% (${uniqueEstabelecimentos.size}/${quantidade})`);
    }

    // Converte Map para array
    const unique = Array.from(uniqueEstabelecimentos.values());

    console.log(`Total coletado: ${unique.length} estabelecimentos únicos (${currentPage} páginas)`);

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
