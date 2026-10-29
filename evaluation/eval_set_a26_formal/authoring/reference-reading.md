# 旧语料前置阅读覆盖

日期：2026-10-27。worktree：story-continuity-a2-6-authoring；分支：eval/a2-6-authoring；阅读基线：ad82ff04cb61277d6370fb6d63b2e3608a2c6d6b。

仅记录旧文件覆盖，不包含新作设定、正文或题目。按主控统一口径，“开头几章”落实为每部第1—2章全文。各阅读者真实阅读章内完整原文，输出截断的初次预览不计为完成；后续按章边界分批重新读取。脚本仅枚举已允许路径并核对字节哈希，不代替内容阅读。

45个既有目录；38份现存README全部全文；7个LF正式目录无README。103个作品文件路径（works 91、sources 12）覆盖第1—2章，共206个章槽。96个文件实际阅读前2章，另7个文件逐字节SHA-256等同于已读文件；实际阅读192章，另读A2t两部第3章及A1c4 w02第3章，共195次整章阅读。跨阅读组的其他重复文字仍按实际重复阅读计，不把96称作全库去重作品数。

阅读分工：reference_audit负责A2/A3；a1c_openings负责A1c系列；checker_read负责早期A1/A1b、LF、v11/v12。

读取前排除eval_set_a3f2_formal、eval_set_a3s2_formal、eval_set_a1_reserve、eval_set_a1b_reserve、eval_set_v13_authoring；未定位或进入前两者，未打开后三者。所有路径均在指定worktree；未调用模型接口、产品或评测。

| 旧目录 | README | 作品路径数 | 前2章覆盖 |
|---|---|---:|---|
| eval_set_a1_dev | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a1_formal | 全文 | 5 | 全覆盖（等同副本见下表） |
| eval_set_a1b_dev | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a1b_formal | 全文 | 3 | 全覆盖（等同副本见下表） |
| eval_set_a1c_dev | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a1c_formal | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a1c2_formal | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a1c3_formal | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a1c4_formal | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a1c5_formal | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a1cr6_formal | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a1cs_formal | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a1cs2_formal | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a1cs3_formal | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a1cs4_formal | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a1cs5_formal | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a1cx_dev | 全文 | 3 | 全覆盖（等同副本见下表） |
| eval_set_a1cy_dev | 全文 | 3 | 全覆盖（等同副本见下表） |
| eval_set_a2_dev | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a2_formal | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a22_formal | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a23_formal | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a24_formal | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a25_formal | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a2s_formal | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a2s2_formal | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a2s3_formal | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a2s4_formal | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a2s5_formal | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a2t_dev | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a3_dev | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a3_formal | 全文 | 2 | 全覆盖（等同副本见下表） |
| eval_set_a3d2_dev | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_a3s_formal | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_lf1_dev | 全文 | 3 | 全覆盖（等同副本见下表） |
| eval_set_lf1_formal | 不存在 | 4 | 全覆盖（等同副本见下表） |
| eval_set_lf1_import | 全文 | 1 | 全覆盖（等同副本见下表） |
| eval_set_lf2_formal | 不存在 | 4 | 全覆盖（等同副本见下表） |
| eval_set_lf3_formal | 不存在 | 4 | 全覆盖（等同副本见下表） |
| eval_set_lf4_formal | 不存在 | 4 | 全覆盖（等同副本见下表） |
| eval_set_lf5_formal | 不存在 | 4 | 全覆盖（等同副本见下表） |
| eval_set_lf6_formal | 不存在 | 4 | 全覆盖（等同副本见下表） |
| eval_set_lf7_formal | 不存在 | 4 | 全覆盖（等同副本见下表） |
| eval_set_v11_authoring | 全文 | 6 | 全覆盖（等同副本见下表） |
| eval_set_v12_authoring | 全文 | 6 | 全覆盖（等同副本见下表） |

## 文件级实际阅读与等同覆盖

| 文件（相对evaluation） | 覆盖 | SHA-256 |
|---|---|---|
| eval_set_a1_dev/works/d01.md | 第1—2章全文实际阅读 | df3fa60cbfcd316de747f49ddabe939706423b3197ef5ff927c8fa0472fead34 |
| eval_set_a1_dev/works/d02.md | 第1—2章全文实际阅读 | 16c1fcd8409ae653f21d56e0d1d37d9a562b7b5650636006f7565c6cbe72c2ca |
| eval_set_a1_formal/works/f01.md | 第1—2章全文实际阅读 | 8997b5b428874306f6e03e1bc97eef3baf4106b7f12e50965709fd31420ad27c |
| eval_set_a1_formal/works/f02.md | 第1—2章全文实际阅读 | 6ae559532b8527f636d71e23e69206903388248608c0b3eea7c1537670d2da36 |
| eval_set_a1_formal/works/f03.md | 第1—2章全文实际阅读 | b5c52ab93bcc28f098345f9cb5e70e7b814004615e20fcf014996823d5c3a544 |
| eval_set_a1_formal/works/f04.md | 第1—2章全文实际阅读 | 6b206b473643c2c7ff5dc1538f4c5c6aef3f45e41d5771a1456c47d9f6a3b9ec |
| eval_set_a1_formal/works/f05.md | 第1—2章全文实际阅读 | 68338c3887dd804dcb02c9dc586db1e75965c94c54ba3c478a7cbb5986ef63e3 |
| eval_set_a1b_dev/works/l1.md | 第1—2章全文实际阅读 | 24681f2160a622110a2401443afffd0cab5d61b4ea0a692378f23c32ef0f8c1b |
| eval_set_a1b_dev/works/s1.md | 第1—2章全文实际阅读 | 22a4e2ad58cda96af08121ae9e7eea7749063165079e22c3a3d9edd98edcfeaf |
| eval_set_a1b_formal/works/l2.md | 第1—2章全文实际阅读 | fefe59487d6b5752b4632a2bcead5b6e3d5113374d51af75abc25f6e40214413 |
| eval_set_a1b_formal/works/n.md | 第1—2章全文实际阅读 | 9bdf60b7317b5b4969f78d78238b2e416d09ab5ea61e1f2a43d5fa3d97f358aa |
| eval_set_a1b_formal/works/s2.md | 第1—2章全文实际阅读 | 0ac3b938c4e1139af6b2b670630789081a3c9c0e44ba1a47598817d9b42d0eb0 |
| eval_set_a1c_dev/works/race.md | 第1—2章全文实际阅读 | 936497c5bc64d52965d2148434cda6812a82c7fba1f73296bc18418cd19d473f |
| eval_set_a1c_formal/works/f1.md | 第1—2章全文实际阅读 | 3abd4641f66b697fb52d5e219367b2e5c082e0edd9cbe1eaa63c7151335465c8 |
| eval_set_a1c_formal/works/f2.md | 第1—2章全文实际阅读 | 016ae68183cc7e3462bad7c2bf6aedf0dc48d6590464ac3293ed70dab4193aa8 |
| eval_set_a1c2_formal/works/w01.md | 第1—2章全文实际阅读 | ce2c5e42a8fa9ae46934c5469ed4975f7a98546c98020c79525f31d0222f3a69 |
| eval_set_a1c2_formal/works/w02.md | 第1—2章全文实际阅读 | 30bb94c8b2062e6d28e3000513d362a85d10ddbfaaecaabc6f7e4e98d41d7cf7 |
| eval_set_a1c3_formal/works/w01.md | 第1—2章全文实际阅读 | f40520ca0a9185a2b04e208df2fa26a16fecac03800a61fc132239f7c3701f13 |
| eval_set_a1c3_formal/works/w02.md | 第1—2章全文实际阅读 | 8aa856872ed45a4b7877a05e73b8764aaa923ad5e46c4f2a0eb12c5c1f74c92a |
| eval_set_a1c4_formal/works/w01.md | 第1—2章全文实际阅读 | 57b0ea162cf1da01736e31c461ad66ea9ba19f6541df5ee90a00eaeaba8104e1 |
| eval_set_a1c4_formal/works/w02.md | 第1—3章全文实际阅读 | b38b250cad65efe935a1b71c6d4f8166c76e1aa0e2316dc1492c3f104dbaf67a |
| eval_set_a1c5_formal/works/w01.md | 第1—2章全文实际阅读 | 3ecd6e94353b2e70a2354be2e31d509e6f6bf4e326fe17fc6bdc1e409aa530bf |
| eval_set_a1c5_formal/works/w02.md | 第1—2章全文实际阅读 | 7c974259864f0e69dd912eaa041c73eb8c411d87bd68c3f48e9bdc0998eccdd9 |
| eval_set_a1cr6_formal/works/w01.md | 第1—2章与已读 eval_set_a1c5_formal/works/w01.md 字节等同 | 3ecd6e94353b2e70a2354be2e31d509e6f6bf4e326fe17fc6bdc1e409aa530bf |
| eval_set_a1cr6_formal/works/w02.md | 第1—2章与已读 eval_set_a1c5_formal/works/w02.md 字节等同 | 7c974259864f0e69dd912eaa041c73eb8c411d87bd68c3f48e9bdc0998eccdd9 |
| eval_set_a1cs_formal/works/lumen.md | 第1—2章全文实际阅读 | 4736914ebafa91bf02e0e487e0074268fad629fbae1863060db7075c38f80908 |
| eval_set_a1cs2_formal/works/safe.md | 第1—2章全文实际阅读 | 7d0997884dd109a4e1babfc996ca922dfc908bd7c1e26c4a1a4977eae9025e8b |
| eval_set_a1cs3_formal/works/safe.md | 第1—2章全文实际阅读 | 51ee7292adddca1a11ebfddd862bcfae3147f90d78fa3a0711b215fd34c46c7d |
| eval_set_a1cs4_formal/works/w03.md | 第1—2章全文实际阅读 | ae016ec40d0290bfeb31e4d3b3e7a424dc63d53843a2b9ddb9d4da182114b36e |
| eval_set_a1cs5_formal/works/w03.md | 第1—2章全文实际阅读 | 39c536311ad353d504de018b425b17dbe15ee749d902b3e4e2e556162b360ca7 |
| eval_set_a1cx_dev/works/cistern.md | 第1—2章全文实际阅读 | 4f11cea18e71c48fe41bb7ca3702be944f9c7f0784bf3759ff8e6f64b07b6711 |
| eval_set_a1cx_dev/works/folio.md | 第1—2章全文实际阅读 | f467faba2b03e38044df59e4305439f8d0cc7c0384678720aa44d47249e6f399 |
| eval_set_a1cx_dev/works/moriri.md | 第1—2章全文实际阅读 | 4ca32199a1883bb17f21181361c6881a931398485c82f0f8b4a84b6124b5d6d6 |
| eval_set_a1cy_dev/works/w01.md | 第1—2章与已读 eval_set_a1c4_formal/works/w01.md 字节等同 | 57b0ea162cf1da01736e31c461ad66ea9ba19f6541df5ee90a00eaeaba8104e1 |
| eval_set_a1cy_dev/works/w02.md | 第1—2章与已读 eval_set_a1c4_formal/works/w02.md 字节等同 | b38b250cad65efe935a1b71c6d4f8166c76e1aa0e2316dc1492c3f104dbaf67a |
| eval_set_a1cy_dev/works/w03.md | 第1—2章与已读 eval_set_a1cs4_formal/works/w03.md 字节等同 | ae016ec40d0290bfeb31e4d3b3e7a424dc63d53843a2b9ddb9d4da182114b36e |
| eval_set_a2_dev/works/w01.md | 第1—2章全文实际阅读 | 46d17210f1e59e64005e417fddda5ec9901a3a636b3bdb6227776f068d08e036 |
| eval_set_a2_formal/works/w01.md | 第1—2章全文实际阅读 | 070a30a534376c61e8d652573a3e4cee6662e29bf24fa13ee1c3795e8dc4c5e3 |
| eval_set_a2_formal/works/w02.md | 第1—2章全文实际阅读 | 2af3a78c61d7461840f2380559fe2b4208d4f20191fe4c32fdb43c85dea1a93a |
| eval_set_a22_formal/works/w01.md | 第1—2章全文实际阅读 | b8b902032371b2f36ecb83e2529feb4b5b2c4192ec0d8b012208b3e105d3bc12 |
| eval_set_a22_formal/works/w02.md | 第1—2章全文实际阅读 | 0647b7814335459f59ca401cd250c6a0b2308816cfe83cbe4a5ac837868e962f |
| eval_set_a23_formal/works/w01.md | 第1—2章与已读 eval_set_a2t_dev/works/w01.md 字节等同 | a418c6baa96657c6204bf5c332f2ee42bd2898579d390b1c697560bba96f310e |
| eval_set_a23_formal/works/w02.md | 第1—2章全文实际阅读 | 25930bd407b4964291550a022d30a8d0db15e9a57c7a0f0f72f0be159c5d6cb5 |
| eval_set_a24_formal/works/w01.md | 第1—2章与已读 eval_set_a2t_dev/works/w02.md 字节等同 | 9d9c894b094be465b2a3cc8d905002f21d76ac0cac9660f34e3ec085d07c2d28 |
| eval_set_a24_formal/works/w02.md | 第1—2章全文实际阅读 | 2dd689cf4a86f76530abd8bbb1e44383c5df6eed992e8f5361df0b0bb408a2de |
| eval_set_a25_formal/works/w01.md | 第1—2章全文实际阅读 | 1af20081b85cf0c9f6d025fa67b0ed1f369b1794a670e075c6bac2d195e66c28 |
| eval_set_a25_formal/works/w02.md | 第1—2章全文实际阅读 | 0360733336dcc46f4d0b8135c8850b960f69ef729c10191429cd833f0530238e |
| eval_set_a2s_formal/works/w01.md | 第1—2章全文实际阅读 | 56baa5f817212dc4480c8a6f8c933167e699661dde2a77ead6fdc8aea2cc7f60 |
| eval_set_a2s2_formal/works/w01.md | 第1—2章全文实际阅读 | 756606da75c07bbe5772f0d879b06fa8f474efdb710841b96a02dd8a4fa45f70 |
| eval_set_a2s3_formal/works/w01.md | 第1—2章全文实际阅读 | e68e007966fca6d23409961ef8d4c71cbfdc69f24e8fd549b86775ea34edc8f1 |
| eval_set_a2s4_formal/works/w01.md | 第1—2章全文实际阅读 | 1303c15edfd861a582bf0cb2b8e450d02e11cb5ef3ed5b4d8fbcef32057fc27e |
| eval_set_a2s5_formal/works/w01.md | 第1—2章全文实际阅读 | 5c6812b6bb7f0e346649b687b2e275b98434639e357f7f68e5da2cfd18de314d |
| eval_set_a2t_dev/works/w01.md | 第1—3章全文实际阅读 | a418c6baa96657c6204bf5c332f2ee42bd2898579d390b1c697560bba96f310e |
| eval_set_a2t_dev/works/w02.md | 第1—3章全文实际阅读 | 9d9c894b094be465b2a3cc8d905002f21d76ac0cac9660f34e3ec085d07c2d28 |
| eval_set_a3_dev/works/w01.md | 第1—2章全文实际阅读 | 25c020a0ddd97ad3771c7d5fba459bdfa5afd2b1caf3f9e4455295597945b8aa |
| eval_set_a3_formal/works/w01.md | 第1—2章全文实际阅读 | 68739d57fe50971e7b569b29be243835d48890e6085d8af481a41c25b79c8672 |
| eval_set_a3_formal/works/w02.md | 第1—2章全文实际阅读 | d16fc9678f35fb6bf85875e052a2f9b83cec95610c11f738921dccc280569d7b |
| eval_set_a3d2_dev/works/w01.md | 第1—2章全文实际阅读 | 3f32a399134c04b07e3abac5f27218828f9ac94b87dc6ca4c1d163bff0e73ef0 |
| eval_set_a3s_formal/works/w01.md | 第1—2章全文实际阅读 | 16a537ebc77cb01abb0ec1e7e916fdd0eb5d91d675123e5ac2d9011428be7a0a |
| eval_set_lf1_dev/works/chaochi_letters.md | 第1—2章全文实际阅读 | 45a35d8197bebb913575f69f3ecc5ab73bc2433bb31b5b25451456a9d4621f78 |
| eval_set_lf1_dev/works/shahai_error.md | 第1—2章全文实际阅读 | fd39de1fbf4e189a397bc99646b5749e6a76dadab2f8649bbb9faa7c742486b5 |
| eval_set_lf1_dev/works/yechu_orders.md | 第1—2章全文实际阅读 | 59b74735ebe403736c1965408157c1a9dd2ff9272b1159105a7a732b93464653 |
| eval_set_lf1_formal/works/canal_records.md | 第1—2章全文实际阅读 | b2ad28ee5a18e4bf36df658666384c09765600c0ad9e55e105c52c7edf1ebc1e |
| eval_set_lf1_formal/works/clay_theatre.md | 第1—2章全文实际阅读 | 0c9fb25e3f0cd292e767685305065457dd6b3b40ce2034d8cc7f6ecbe0eb4eee |
| eval_set_lf1_formal/works/moss_cape.md | 第1—2章全文实际阅读 | 91c9c1bd90e155ef004019874eac7face13c13308379984d002ec976d73a3b6a |
| eval_set_lf1_formal/works/orbital_orchard.md | 第1—2章全文实际阅读 | 07c86a435beaed2f94915b1b8263150b7d57b5a3c5901563be16ce8cdf7d8cb2 |
| eval_set_lf1_import/works/moriri_cleaner.md | 第1—2章全文实际阅读 | a1c4e7e3d77a9f8c6717bf98df9faeedbc77c871adb1803cb791e78cb979ceda |
| eval_set_lf2_formal/works/folded_folio.md | 第1—2章全文实际阅读 | f467faba2b03e38044df59e4305439f8d0cc7c0384678720aa44d47249e6f399 |
| eval_set_lf2_formal/works/resonant_cistern.md | 第1—2章全文实际阅读 | 4f11cea18e71c48fe41bb7ca3702be944f9c7f0784bf3759ff8e6f64b07b6711 |
| eval_set_lf2_formal/works/switchyard_fern.md | 第1—2章全文实际阅读 | 38b34de78b8f4a8606b6276546ed8430bb7526a94029735a8101b1f428daad51 |
| eval_set_lf2_formal/works/upland_fieldnotes.md | 第1—2章全文实际阅读 | af5c960077b260713e3c36367f640bf72e315d331c268a8606031e555d630b2f |
| eval_set_lf3_formal/works/felt_ferry.md | 第1—2章全文实际阅读 | 0ad831904fc0019e757127980580d14f5f0189c1348da94cfb0af01ed83e0e99 |
| eval_set_lf3_formal/works/sand_sail.md | 第1—2章全文实际阅读 | d1e99c3d94f2c0685bbb775c75837e8c63958dfd95b32f2b47bc30cd4bafb670 |
| eval_set_lf3_formal/works/spore_circuit.md | 第1—2章全文实际阅读 | 29374d366c2711e30f7b1a8a1d1d8504a34b6d4b956fc387d382ea0cddf257ed |
| eval_set_lf3_formal/works/submerged_room.md | 第1—2章全文实际阅读 | 4790d4b98d2bff9c3d7c9b729043bebdb56bb5b857a821eab51df700a8e7852f |
| eval_set_lf4_formal/works/chaomu.md | 第1—2章全文实际阅读 | b981d32d389b32de7addb7dff48a9bad06b0d2cd50ae5dd28172da2734c641d4 |
| eval_set_lf4_formal/works/chiji.md | 第1—2章全文实际阅读 | 8fe86faf3b96845a7eadd54684c228c50151423eac1ff24dccd6989b45aa2b37 |
| eval_set_lf4_formal/works/weiwan.md | 第1—2章全文实际阅读 | 93511e11ac1ef36e0dcf0eef1389c4e819863568fcecd684164acf3edf6888f3 |
| eval_set_lf4_formal/works/zhuxiang.md | 第1—2章全文实际阅读 | 08c3fe49164121dfdb4d1e1ee55d1c21425155a6df4e7650270914df3a31cf0c |
| eval_set_lf5_formal/works/huli_mail.md | 第1—2章全文实际阅读 | be0b8b4e83b1259e039eb80d212af77af42b0e0577d47898dce0dc80526eae12 |
| eval_set_lf5_formal/works/rongji_stage.md | 第1—2章全文实际阅读 | 4e1221383497f375a90a880084151d59ad18a8c06098fdb32114ecb2d161a92d |
| eval_set_lf5_formal/works/taijie_rain.md | 第1—2章全文实际阅读 | c3ae1927512262aaa70df9848fd9b42d8990f1cb787a1da50557565dce013d68 |
| eval_set_lf5_formal/works/xiuzi_school.md | 第1—2章全文实际阅读 | 098afacd0a4a9ab04feb98ab89f4e8fd9352c6c60c29eeebb92ad8abef25c033 |
| eval_set_lf6_formal/works/fengnang.md | 第1—2章全文实际阅读 | c6ad1dc8d824734550ce0d66598b43427a61e2b4985351b64c286253394ed7e0 |
| eval_set_lf6_formal/works/hanceng.md | 第1—2章全文实际阅读 | ac2a070e4d1507de95d5b74208aa234cfe95bed32a48df1a3dad88b29a970f3e |
| eval_set_lf6_formal/works/rongwen.md | 第1—2章全文实际阅读 | ca2272be064612a5aa6bf46d9a594f211f128c50b8a2fa0c35086b2d82f90c05 |
| eval_set_lf6_formal/works/yingxiang.md | 第1—2章全文实际阅读 | 35d7a42a8d98e571c18a0180df2873b7f9a75ccc4c3489f656e1ec5f1d0c3922 |
| eval_set_lf7_formal/works/huixiang.md | 第1—2章全文实际阅读 | 9466cd04b5f584308dfc5e3d1e2129c2cedc7a803e15eff84fec7120a6d2ba2d |
| eval_set_lf7_formal/works/juzao.md | 第1—2章全文实际阅读 | 88ed2236baa89f8ffe3b2324ea2caa3154128deb17833d7b8dc0bc83a05dae5e |
| eval_set_lf7_formal/works/yishou.md | 第1—2章全文实际阅读 | 31b2ee148eb75942e879e488a82b0884f19e40b3e9de44017d89de766dbd5d72 |
| eval_set_lf7_formal/works/yueji.md | 第1—2章全文实际阅读 | ab1f07078ec3f9253e4064955cb98beecf245e7a036b234dba5c89f4f6f1a8b1 |
| eval_set_v11_authoring/sources/huangting_recording.md | 第1—2章全文实际阅读 | fa8003d39a8624f881e7ba9ad70ebfaf7c153c2709bffa890a3563767abba654 |
| eval_set_v11_authoring/sources/jinyu_credit_market.md | 第1—2章全文实际阅读 | 217d02a45ffae9b9e4adb9247fb4ec375500ac50f3a02fcccc762dd9682ccbbe |
| eval_set_v11_authoring/sources/luliao_last_collection.md | 第1—2章全文实际阅读 | 8d599daf38916bb6f1a264efb4bb24c16efd86e35ac894bb58c3252d636b482c |
| eval_set_v11_authoring/sources/mosswick_costume_rental.md | 第1—2章全文实际阅读 | ef1e37a224cba7c3f63151fda4792dd987b39d5ab8756d372c565f5e6e764d0e |
| eval_set_v11_authoring/sources/sablefen_translation_residency.md | 第1—2章全文实际阅读 | 8d1b4ea2db89f77b0abbc0845b364958f4ed5a3ba3a0e5766d8eaac00e04ba2e |
| eval_set_v11_authoring/sources/ternhollow_model_railway.md | 第1—2章全文实际阅读 | 033368c73a0b1e24ba60fe2016475cbc10c712958e61e620de939e76f0af47ae |
| eval_set_v12_authoring/sources/brambletide_aquarium_census.md | 第1—2章全文实际阅读 | 6ec74dd67f833d732e890edca0bcf0e7c8ac42f6bc3939168815d5530d9e020d |
| eval_set_v12_authoring/sources/calverin_rag_paper_mill.md | 第1—2章全文实际阅读 | 09c1a7f76bbef78e83db63a93ee6d33ba506e9e163fbce051729297834376601 |
| eval_set_v12_authoring/sources/elmrake_hotel_repairs.md | 第1—2章全文实际阅读 | 4be8e8ea80a2a7320ae91bd25d3e224d5b2491ba950319e93d3610d385a55ab9 |
| eval_set_v12_authoring/sources/puling_refraction_festival.md | 第1—2章全文实际阅读 | 17cd5275b55533c5dbe68fcbaba8976bea51fa9d19113950f4a78d152160c447 |
| eval_set_v12_authoring/sources/shengxiu_score_library.md | 第1—2章全文实际阅读 | f4dfe4b1bfef1597ce9568631574d1584e397d40980d9542f2dce8d9852abff0 |
| eval_set_v12_authoring/sources/tiaojin_rainworks.md | 第1—2章全文实际阅读 | d4632f8255a835322cebf4d77eb944e500f57817e38be617c386179e3c1700a2 |
