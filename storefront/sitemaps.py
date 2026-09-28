from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .models import Category, Product


class ProductSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return Product.objects.filter(is_active=True).order_by("pk")

    def lastmod(self, product):
        return product.updated_at


class CategorySitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        return Category.objects.order_by("pk")

    def location(self, category):
        return reverse("storefront:category", args=[category.slug])


class StaticPageSitemap(Sitemap):
    priority = 0.5

    def items(self):
        return [("storefront:home", []), ("storefront:product_list", []),
                ("storefront:trust_page", ["returns"]), ("storefront:trust_page", ["privacy"]),
                ("storefront:trust_page", ["terms"])]

    def location(self, item):
        name, args = item
        return reverse(name, args=args)


SITEMAPS = {"products": ProductSitemap, "categories": CategorySitemap, "pages": StaticPageSitemap}
