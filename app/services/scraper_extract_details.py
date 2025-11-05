async def _extract_business_details(page) -> Dict[str, Optional[str]]:
    """
    Extract comprehensive business details from a listing page.
    Returns a dict with name, address, category, etc.
    """
    if not _page_alive(page):
        return {"name": None, "address": None, "category": None}
    
    details = {
        "name": None,
        "address": None,
        "category": None,
        "additional": None
    }
    
    try:
        # Extract name using multiple methods
        # 1. meta[itemprop='name'] - most reliable when present
        meta = await page.locator("meta[itemprop='name']").count()
        if meta > 0:
            content = await page.locator("meta[itemprop='name']").first.get_attribute("content")
            if content and content.strip():
                details["name"] = content.strip()
        
        # 2. Try primary name selectors
        if not details["name"]:
            for sel in [s for s in PRIMARY_NAME_SELECTORS if "::attr" not in s and "meta" not in s]:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    text = await loc.first.text_content()
                    if text and text.strip():
                        details["name"] = text.strip()
                        break
        
        # 3. Last resort: title
        if not details["name"]:
            title_loc = page.locator("title")
            if await title_loc.count() > 0:
                t = (await title_loc.first.text_content()) or ""
                t = t.replace(" - Google Maps", "").replace(" – Google Maps", "")
                t = t.replace(" - Pesquisa Google", "").replace(" – Pesquisa Google", "")
                t = t.strip()
                if t:
                    details["name"] = t
        
        # Extract address - helps differentiate similar businesses
        address_selectors = [
            "[data-item-id='address']",
            "[data-attrid='kc:/location/location:address']",
            ".rogA2c",
            ".LrzXr",
            "[aria-label*='Endereço']",
            "[aria-label*='Address']"
        ]
        
        for sel in address_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0:
                text = await loc.first.text_content()
                if text and text.strip():
                    details["address"] = text.strip()
                    break
        
        # Extract category/type
        category_selectors = [
            "[jsaction*='pane.rating.category']",
            ".YhemCb",
            "[data-attrid='kc:/local:one line summary']",
            ".dbg0pd + div",
            "[aria-label*='Categoria']"
        ]
        
        for sel in category_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0:
                text = await loc.first.text_content()
                if text and text.strip():
                    details["category"] = text.strip()
                    break
                    
        # Try additional descriptive text as fallback
        if not details["category"]:
            desc_selectors = [
                ".PYvSYb",
                ".IEKGEb",
                ".lqhpac"
            ]
            for sel in desc_selectors:
                loc = page.locator(sel)
                if await loc.count() > 0:
                    text = await loc.first.text_content()
                    if text and text.strip():
                        details["additional"] = text.strip()
                        break
                        
    except Exception as e:
        log.debug(f"Error extracting business details: {e}")
    
    return details

# Substitui a função original para manter compatibilidade
async def _primary_business_name(page) -> Optional[str]:
    """
    Return the main business name when on the listing detail page (Google Maps card).
    Prioritises the exact card title and safe fallbacks.
    """
    details = await _extract_business_details(page)
    return details.get("name")
