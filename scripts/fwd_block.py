#: `即将发布` / `准备发布` / `预告` name a release that has not happened yet. The verb matcher
#: sees 发布 and files them under 模型发布, putting an announcement of a future launch beside the
#: launches themselves -- on 2026-10-19 two such items outranked the real releases.
_FORWARD_LOOKING = re.compile(
    r"即将(?:发布|推出|上线|开源|到来)|准备(?:发布|推出)|预告|预热|定档|将于"
    r"|(?:将|拟|计划)于?[^，。]{0,12}(?:发布|推出|上线)"
    r"|coming soon|will (?:be )?(?:release|launch|ship)|expected to (?:release|launch)",
    re.I,
)

