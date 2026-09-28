from crawler import extract_links, extract_product_no, parse_product


def test_extract_product_no_cafe24_urls():
    assert extract_product_no("https://shop.test/product/name/49/category/1/display/6/") == "49"
    assert extract_product_no("https://shop.test/product/detail.html?product_no=123&cate_no=1") == "123"


def test_extract_links():
    html = '''
    <a href="/product/alpha/49/category/1/display/1/">A</a>
    <a href="/product/detail.html?product_no=50&cate_no=1">B</a>
    <a href="/product/list.html?cate_no=24">Category</a>
    '''
    products, categories = extract_links(html, "https://vibecodinguniv.cafe24.com/")
    assert set(products) == {"49", "50"}
    assert any("cate_no=24" in x for x in categories)


def test_parse_product_common_cafe24_markup():
    html = '''
    <html><head>
      <meta property="og:image" content="//img.example.com/p.jpg">
      <meta name="description" content="테스트 상품 설명">
    </head><body>
      <div class="xans-product-detail"><div class="headingArea"><h2>시그니처 메탈 볼펜</h2></div></div>
      <table>
        <tr><th>상품코드</th><td>P00000BV</td></tr>
        <tr><th>소비자가</th><td>19,900원</td></tr>
        <tr><th>판매가</th><td>16,900원</td></tr>
      </table>
      <div class="path"><a>홈</a><a>문구</a><a>볼펜</a></div>
    </body></html>
    '''
    p = parse_product(html, "https://vibecodinguniv.cafe24.com/product/pen/49/category/1/display/1/")
    assert p is not None
    assert p.source_product_no == "49"
    assert p.name == "시그니처 메탈 볼펜"
    assert p.price == 16900
    assert p.original_price == 19900
    assert p.product_code == "P00000BV"
    assert p.image_url == "https://img.example.com/p.jpg"
    assert p.category == "문구 > 볼펜"
