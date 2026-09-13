# Matcher Index

Every name in the AST Matcher Reference, and the lab section that covers it.
Names are grouped as the reference groups them. `✗` marks names not
registered in clang-query 22 (their entries explain the alternative).

## Node matchers (226)

| Matcher | Returns | Where | |
|---|---|---|---|
| `accessSpecDecl` | `Decl` | [§2.3](part_2_node_matchers_decls.md) |  |
| `addrLabelExpr` | `Stmt` | [§3.10](part_3_node_matchers_stmts.md) |  |
| `arrayInitIndexExpr` | `Stmt` | [§3.7](part_3_node_matchers_stmts.md) |  |
| `arrayInitLoopExpr` | `Stmt` | [§3.7](part_3_node_matchers_stmts.md) |  |
| `arraySubscriptExpr` | `Stmt` | [§3.4](part_3_node_matchers_stmts.md) |  |
| `arrayType` | `Type` | [§4.3](part_4_node_matchers_types.md) |  |
| `arrayTypeLoc` | `TypeLoc` | [§4.9](part_4_node_matchers_types.md) |  |
| `asmStmt` | `Stmt` | [§3.10](part_3_node_matchers_stmts.md) |  |
| `atomicExpr` | `Stmt` | [§3.10](part_3_node_matchers_stmts.md) |  |
| `atomicType` | `Type` | [§4.8](part_4_node_matchers_types.md) |  |
| `attr` | `Attr` | [§2.7](part_2_node_matchers_decls.md) |  |
| `autoType` | `Type` | [§4.8](part_4_node_matchers_types.md) |  |
| `autoreleasePoolStmt` | `Stmt` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `binaryConditionalOperator` | `Stmt` | [§3.4](part_3_node_matchers_stmts.md) |  |
| `binaryOperator` | `Stmt` | [§3.4](part_3_node_matchers_stmts.md) |  |
| `bindingDecl` | `Decl` | [§2.3](part_2_node_matchers_decls.md) |  |
| `blockDecl` | `Decl` | [§11.6](part_11_objc_openmp_cuda_blocks.md) |  |
| `blockExpr` | `Stmt` | [§11.6](part_11_objc_openmp_cuda_blocks.md) |  |
| `blockPointerType` | `Type` | [§11.6](part_11_objc_openmp_cuda_blocks.md) |  |
| `breakStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `builtinType` | `Type` | [§4.2](part_4_node_matchers_types.md) |  |
| `cStyleCastExpr` | `Stmt` | [§3.6](part_3_node_matchers_stmts.md) |  |
| `callExpr` | `Stmt` | [§3.5](part_3_node_matchers_stmts.md) |  |
| `caseStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `castExpr` | `Stmt` | [§3.6](part_3_node_matchers_stmts.md) |  |
| `characterLiteral` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `chooseExpr` | `Stmt` | [§3.10](part_3_node_matchers_stmts.md) |  |
| `classTemplateDecl` | `Decl` | [§2.4](part_2_node_matchers_decls.md) |  |
| `classTemplatePartialSpecializationDecl` | `Decl` | [§2.4](part_2_node_matchers_decls.md) |  |
| `classTemplateSpecializationDecl` | `Decl` | [§2.4](part_2_node_matchers_decls.md) |  |
| `coawaitExpr` | `Stmt` | [§3.9](part_3_node_matchers_stmts.md) |  |
| `complexType` | `Type` | [§4.8](part_4_node_matchers_types.md) |  |
| `compoundLiteralExpr` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `compoundStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `conceptDecl` | `Decl` | [§2.4](part_2_node_matchers_decls.md) |  |
| `conditionalOperator` | `Stmt` | [§3.4](part_3_node_matchers_stmts.md) |  |
| `constantArrayType` | `Type` | [§4.3](part_4_node_matchers_types.md) |  |
| `constantExpr` | `Stmt` | [§3.7](part_3_node_matchers_stmts.md) |  |
| `continueStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `convertVectorExpr` | `Stmt` | [§3.10](part_3_node_matchers_stmts.md) |  |
| `coreturnStmt` | `Stmt` | [§3.9](part_3_node_matchers_stmts.md) |  |
| `coroutineBodyStmt` | `Stmt` | [§3.9](part_3_node_matchers_stmts.md) |  |
| `coyieldExpr` | `Stmt` | [§3.9](part_3_node_matchers_stmts.md) |  |
| `cudaKernelCallExpr` | `Stmt` | [§11.5](part_11_objc_openmp_cuda_blocks.md) |  |
| `cxxBaseSpecifier` | `CXXBaseSpecifier` | [§2.7](part_2_node_matchers_decls.md) |  |
| `cxxBindTemporaryExpr` | `Stmt` | [§3.7](part_3_node_matchers_stmts.md) |  |
| `cxxBoolLiteral` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `cxxCatchStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `cxxConstCastExpr` | `Stmt` | [§3.6](part_3_node_matchers_stmts.md) |  |
| `cxxConstructExpr` | `Stmt` | [§3.5](part_3_node_matchers_stmts.md) |  |
| `cxxConstructorDecl` | `Decl` | [§2.2](part_2_node_matchers_decls.md) |  |
| `cxxConversionDecl` | `Decl` | [§2.2](part_2_node_matchers_decls.md) |  |
| `cxxCtorInitializer` | `CXXCtorInitializer` | [§2.7](part_2_node_matchers_decls.md) |  |
| `cxxDeductionGuideDecl` | `Decl` | [§2.2](part_2_node_matchers_decls.md) |  |
| `cxxDefaultArgExpr` | `Stmt` | [§3.5](part_3_node_matchers_stmts.md) |  |
| `cxxDeleteExpr` | `Stmt` | [§3.5](part_3_node_matchers_stmts.md) |  |
| `cxxDependentScopeMemberExpr` | `Stmt` | [§3.8](part_3_node_matchers_stmts.md) |  |
| `cxxDestructorDecl` | `Decl` | [§2.2](part_2_node_matchers_decls.md) |  |
| `cxxDynamicCastExpr` | `Stmt` | [§3.6](part_3_node_matchers_stmts.md) |  |
| `cxxFoldExpr` | `Stmt` | [§3.4](part_3_node_matchers_stmts.md) |  |
| `cxxForRangeStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `cxxFunctionalCastExpr` | `Stmt` | [§3.6](part_3_node_matchers_stmts.md) |  |
| `cxxMemberCallExpr` | `Stmt` | [§3.5](part_3_node_matchers_stmts.md) |  |
| `cxxMethodDecl` | `Decl` | [§2.2](part_2_node_matchers_decls.md) |  |
| `cxxNamedCastExpr` | `Stmt` | [§3.6](part_3_node_matchers_stmts.md) | ✗ |
| `cxxNewExpr` | `Stmt` | [§3.5](part_3_node_matchers_stmts.md) |  |
| `cxxNoexceptExpr` | `Stmt` | [§3.4](part_3_node_matchers_stmts.md) |  |
| `cxxNullPtrLiteralExpr` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `cxxOperatorCallExpr` | `Stmt` | [§3.4](part_3_node_matchers_stmts.md) |  |
| `cxxRecordDecl` | `Decl` | [§2.3](part_2_node_matchers_decls.md) |  |
| `cxxReinterpretCastExpr` | `Stmt` | [§3.6](part_3_node_matchers_stmts.md) |  |
| `cxxRewrittenBinaryOperator` | `Stmt` | [§3.4](part_3_node_matchers_stmts.md) |  |
| `cxxStaticCastExpr` | `Stmt` | [§3.6](part_3_node_matchers_stmts.md) |  |
| `cxxStdInitializerListExpr` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `cxxTemporaryObjectExpr` | `Stmt` | [§3.5](part_3_node_matchers_stmts.md) |  |
| `cxxThisExpr` | `Stmt` | [§3.3](part_3_node_matchers_stmts.md) |  |
| `cxxThrowExpr` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `cxxTryStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `cxxUnresolvedConstructExpr` | `Stmt` | [§3.8](part_3_node_matchers_stmts.md) |  |
| `decayedType` | `Type` | [§4.3](part_4_node_matchers_types.md) |  |
| `decl` | `Decl` | [§2.1](part_2_node_matchers_decls.md) |  |
| `declRefExpr` | `Stmt` | [§3.3](part_3_node_matchers_stmts.md) |  |
| `declStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `declaratorDecl` | `Decl` | [§2.1](part_2_node_matchers_decls.md) |  |
| `decltypeType` | `Type` | [§4.8](part_4_node_matchers_types.md) |  |
| `decompositionDecl` | `Decl` | [§2.3](part_2_node_matchers_decls.md) |  |
| `deducedTemplateSpecializationType` | `Type` | [§4.7](part_4_node_matchers_types.md) |  |
| `defaultStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `dependentCoawaitExpr` | `Stmt` | [§3.9](part_3_node_matchers_stmts.md) |  |
| `dependentNameType` | `Type` | [§4.7](part_4_node_matchers_types.md) |  |
| `dependentScopeDeclRefExpr` | `Stmt` | [§3.8](part_3_node_matchers_stmts.md) |  |
| `dependentSizedArrayType` | `Type` | [§4.3](part_4_node_matchers_types.md) |  |
| `dependentSizedExtVectorType` | `Type` | [§4.3](part_4_node_matchers_types.md) |  |
| `designatedInitExpr` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `doStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `enumConstantDecl` | `Decl` | [§2.5](part_2_node_matchers_decls.md) |  |
| `enumDecl` | `Decl` | [§2.5](part_2_node_matchers_decls.md) |  |
| `enumType` | `Type` | [§4.5](part_4_node_matchers_types.md) |  |
| `explicitCastExpr` | `Stmt` | [§3.6](part_3_node_matchers_stmts.md) |  |
| `exportDecl` | `Decl` | [§2.6](part_2_node_matchers_decls.md) |  |
| `expr` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `exprWithCleanups` | `Stmt` | [§3.7](part_3_node_matchers_stmts.md) |  |
| `fieldDecl` | `Decl` | [§2.3](part_2_node_matchers_decls.md) |  |
| `fileScopeAsmDecl` | `Decl` | [§2.1](part_2_node_matchers_decls.md) |  |
| `fixedPointLiteral` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `floatLiteral` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `forStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `friendDecl` | `Decl` | [§2.3](part_2_node_matchers_decls.md) |  |
| `functionDecl` | `Decl` | [§2.2](part_2_node_matchers_decls.md) |  |
| `functionProtoType` | `Type` | [§4.4](part_4_node_matchers_types.md) |  |
| `functionTemplateDecl` | `Decl` | [§2.4](part_2_node_matchers_decls.md) |  |
| `functionType` | `Type` | [§4.4](part_4_node_matchers_types.md) |  |
| `functionTypeLoc` | `TypeLoc` | [§4.9](part_4_node_matchers_types.md) | ✗ |
| `genericSelectionExpr` | `Stmt` | [§3.10](part_3_node_matchers_stmts.md) |  |
| `gnuNullExpr` | `Stmt` | [§3.10](part_3_node_matchers_stmts.md) |  |
| `gotoStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `ifStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `imaginaryLiteral` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `implicitCastExpr` | `Stmt` | [§3.6](part_3_node_matchers_stmts.md) |  |
| `implicitValueInitExpr` | `Stmt` | [§3.7](part_3_node_matchers_stmts.md) |  |
| `incompleteArrayType` | `Type` | [§4.3](part_4_node_matchers_types.md) |  |
| `indirectFieldDecl` | `Decl` | [§2.3](part_2_node_matchers_decls.md) |  |
| `initListExpr` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `injectedClassNameType` | `Type` | [§4.7](part_4_node_matchers_types.md) |  |
| `integerLiteral` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `lValueReferenceType` | `Type` | [§4.2](part_4_node_matchers_types.md) |  |
| `labelDecl` | `Decl` | [§2.2](part_2_node_matchers_decls.md) |  |
| `labelStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `lambdaCapture` | `LambdaCapture` | [§2.7](part_2_node_matchers_decls.md) |  |
| `lambdaExpr` | `Stmt` | [§3.5](part_3_node_matchers_stmts.md) |  |
| `linkageSpecDecl` | `Decl` | [§2.6](part_2_node_matchers_decls.md) |  |
| `macroQualifiedType` | `Type` | [§4.6](part_4_node_matchers_types.md) |  |
| `materializeTemporaryExpr` | `Stmt` | [§3.7](part_3_node_matchers_stmts.md) |  |
| `memberExpr` | `Stmt` | [§3.3](part_3_node_matchers_stmts.md) |  |
| `memberPointerType` | `Type` | [§4.2](part_4_node_matchers_types.md) |  |
| `namedDecl` | `Decl` | [§2.1](part_2_node_matchers_decls.md) |  |
| `namespaceAliasDecl` | `Decl` | [§2.6](part_2_node_matchers_decls.md) |  |
| `namespaceDecl` | `Decl` | [§2.6](part_2_node_matchers_decls.md) |  |
| `nestedNameSpecifier` | `NestedNameSpecifier` | [§4.10](part_4_node_matchers_types.md) |  |
| `nestedNameSpecifierLoc` | `NestedNameSpecifierLoc` | [§4.10](part_4_node_matchers_types.md) |  |
| `nonTypeTemplateParmDecl` | `Decl` | [§2.4](part_2_node_matchers_decls.md) |  |
| `nullStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `objcCatchStmt` | `Stmt` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcCategoryDecl` | `Decl` | [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcCategoryImplDecl` | `Decl` | [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcFinallyStmt` | `Stmt` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcImplementationDecl` | `Decl` | [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcInterfaceDecl` | `Decl` | [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcIvarDecl` | `Decl` | [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcIvarRefExpr` | `Stmt` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcMessageExpr` | `Stmt` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcMethodDecl` | `Decl` | [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcObjectPointerType` | `Type` | [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcPropertyDecl` | `Decl` | [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcProtocolDecl` | `Decl` | [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcStringLiteral` | `Stmt` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcThrowStmt` | `Stmt` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `objcTryStmt` | `Stmt` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `ompCountsClause` | `OMPClause` | [§11.4](part_11_objc_openmp_cuda_blocks.md) | ✗ |
| `ompDefaultClause` | `OMPClause` | [§11.4](part_11_objc_openmp_cuda_blocks.md) |  |
| `ompExecutableDirective` | `Stmt` | [§11.4](part_11_objc_openmp_cuda_blocks.md) |  |
| `ompFromClause` | `OMPClause` | [§11.4](part_11_objc_openmp_cuda_blocks.md) | ✗ |
| `ompSplitDirective` | `Stmt` | [§11.4](part_11_objc_openmp_cuda_blocks.md) | ✗ |
| `ompTargetUpdateDirective` | `Stmt` | [§11.4](part_11_objc_openmp_cuda_blocks.md) | ✗ |
| `ompToClause` | `OMPClause` | [§11.4](part_11_objc_openmp_cuda_blocks.md) | ✗ |
| `opaqueValueExpr` | `Stmt` | [§3.7](part_3_node_matchers_stmts.md) |  |
| `parenExpr` | `Stmt` | [§3.4](part_3_node_matchers_stmts.md) |  |
| `parenListExpr` | `Stmt` | [§3.8](part_3_node_matchers_stmts.md) |  |
| `parenType` | `Type` | [§4.6](part_4_node_matchers_types.md) |  |
| `parmVarDecl` | `Decl` | [§2.2](part_2_node_matchers_decls.md) |  |
| `pointerType` | `Type` | [§4.2](part_4_node_matchers_types.md) |  |
| `pointerTypeLoc` | `TypeLoc` | [§4.9](part_4_node_matchers_types.md) |  |
| `predefinedExpr` | `Stmt` | [§3.10](part_3_node_matchers_stmts.md) |  |
| `qualType` | `QualType` | [§4.1](part_4_node_matchers_types.md) |  |
| `qualifiedTypeLoc` | `TypeLoc` | [§4.9](part_4_node_matchers_types.md) |  |
| `rValueReferenceType` | `Type` | [§4.2](part_4_node_matchers_types.md) |  |
| `recordDecl` | `Decl` | [§2.3](part_2_node_matchers_decls.md) |  |
| `recordType` | `Type` | [§4.5](part_4_node_matchers_types.md) |  |
| `referenceType` | `Type` | [§4.2](part_4_node_matchers_types.md) |  |
| `referenceTypeLoc` | `TypeLoc` | [§4.9](part_4_node_matchers_types.md) |  |
| `requiresExpr` | `Expr` | [§3.8](part_3_node_matchers_stmts.md) | ✗ |
| `requiresExprBodyDecl` | `Decl` | [§2.4](part_2_node_matchers_decls.md) | ✗ |
| `returnStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `staticAssertDecl` | `Decl` | [§2.1](part_2_node_matchers_decls.md) |  |
| `stmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `stmtExpr` | `Stmt` | [§3.10](part_3_node_matchers_stmts.md) |  |
| `stringLiteral` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `substNonTypeTemplateParmExpr` | `Stmt` | [§3.8](part_3_node_matchers_stmts.md) |  |
| `substTemplateTypeParmType` | `Type` | [§4.7](part_4_node_matchers_types.md) |  |
| `switchCase` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `switchStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |
| `tagDecl` | `Decl` | [§2.3](part_2_node_matchers_decls.md) |  |
| `tagType` | `Type` | [§4.5](part_4_node_matchers_types.md) |  |
| `templateArgument` | `TemplateArgument` | [§4.10](part_4_node_matchers_types.md) |  |
| `templateArgumentLoc` | `TemplateArgumentLoc` | [§4.10](part_4_node_matchers_types.md) |  |
| `templateName` | `TemplateName` | [§4.10](part_4_node_matchers_types.md) |  |
| `templateSpecializationType` | `Type` | [§4.7](part_4_node_matchers_types.md) |  |
| `templateSpecializationTypeLoc` | `TypeLoc` | [§4.9](part_4_node_matchers_types.md) |  |
| `templateTemplateParmDecl` | `Decl` | [§2.4](part_2_node_matchers_decls.md) |  |
| `templateTypeParmDecl` | `Decl` | [§2.4](part_2_node_matchers_decls.md) |  |
| `templateTypeParmType` | `Type` | [§4.7](part_4_node_matchers_types.md) |  |
| `translationUnitDecl` | `Decl` | [§2.1](part_2_node_matchers_decls.md) |  |
| `type` | `Type` | [§4.1](part_4_node_matchers_types.md) |  |
| `typeAliasDecl` | `Decl` | [§2.5](part_2_node_matchers_decls.md) |  |
| `typeAliasTemplateDecl` | `Decl` | [§2.5](part_2_node_matchers_decls.md) |  |
| `typeLoc` | `TypeLoc` | [§4.1](part_4_node_matchers_types.md) |  |
| `typedefDecl` | `Decl` | [§2.5](part_2_node_matchers_decls.md) |  |
| `typedefNameDecl` | `Decl` | [§2.5](part_2_node_matchers_decls.md) |  |
| `typedefType` | `Type` | [§4.6](part_4_node_matchers_types.md) |  |
| `unaryExprOrTypeTraitExpr` | `Stmt` | [§3.4](part_3_node_matchers_stmts.md) |  |
| `unaryOperator` | `Stmt` | [§3.4](part_3_node_matchers_stmts.md) |  |
| `unaryTransformType` | `Type` | [§4.8](part_4_node_matchers_types.md) |  |
| `unresolvedLookupExpr` | `Stmt` | [§3.8](part_3_node_matchers_stmts.md) |  |
| `unresolvedMemberExpr` | `Stmt` | [§3.8](part_3_node_matchers_stmts.md) |  |
| `unresolvedUsingTypenameDecl` | `Decl` | [§2.4](part_2_node_matchers_decls.md) |  |
| `unresolvedUsingValueDecl` | `Decl` | [§2.4](part_2_node_matchers_decls.md) |  |
| `userDefinedLiteral` | `Stmt` | [§3.2](part_3_node_matchers_stmts.md) |  |
| `usingDecl` | `Decl` | [§2.5](part_2_node_matchers_decls.md) |  |
| `usingDirectiveDecl` | `Decl` | [§2.5](part_2_node_matchers_decls.md) |  |
| `usingEnumDecl` | `Decl` | [§2.5](part_2_node_matchers_decls.md) |  |
| `usingShadowDecl` | `Decl` | [§2.5](part_2_node_matchers_decls.md) |  |
| `usingType` | `Type` | [§4.6](part_4_node_matchers_types.md) |  |
| `valueDecl` | `Decl` | [§2.1](part_2_node_matchers_decls.md) |  |
| `varDecl` | `Decl` | [§2.6](part_2_node_matchers_decls.md) |  |
| `variableArrayType` | `Type` | [§4.3](part_4_node_matchers_types.md) |  |
| `whileStmt` | `Stmt` | [§3.1](part_3_node_matchers_stmts.md) |  |

## Narrowing matchers (152)

| Matcher | Returns | Where | |
|---|---|---|---|
| `allOf` | `*` | [§5.1](part_5_narrowing_logic_decls.md) |  |
| `anyOf` | `*` | [§5.1](part_5_narrowing_logic_decls.md) |  |
| `anything` | `*` | [§5.1](part_5_narrowing_logic_decls.md) |  |
| `argumentCountAtLeast` | `CXXConstructExpr`, `CXXUnresolvedConstructExpr`, `CallExpr`, `ObjCMessageExpr` | [§6.3](part_6_narrowing_stmts.md), [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `argumentCountIs` | `CXXConstructExpr`, `CXXUnresolvedConstructExpr`, `CallExpr`, `ObjCMessageExpr` | [§6.3](part_6_narrowing_stmts.md), [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `asString` | `QualType` | [§7.1](part_7_narrowing_types_templates_locations.md) |  |
| `booleanType` | `Type` | [§7.1](part_7_narrowing_types_templates_locations.md) |  |
| `capturesThis` | `LambdaCapture` | [§6.7](part_6_narrowing_stmts.md) |  |
| `declCountIs` | `DeclStmt` | [§6.6](part_6_narrowing_stmts.md) |  |
| `declaresSameEntityAsBoundNode` | `Decl` | [§7.5](part_7_narrowing_types_templates_locations.md) |  |
| `designatorCountIs` | `DesignatedInitExpr` | [§6.6](part_6_narrowing_stmts.md) |  |
| `equals` | `CXXBoolLiteralExpr`, `CharacterLiteral`, `FloatingLiteral`, `IntegerLiteral` | [§6.2](part_6_narrowing_stmts.md) |  |
| `equalsBoundNode` | `Decl`, `QualType`, `Stmt`, `Type` | [§7.5](part_7_narrowing_types_templates_locations.md) |  |
| `equalsIntegralValue` | `TemplateArgument` | [§7.3](part_7_narrowing_types_templates_locations.md) |  |
| `equalsNode` | `Decl`, `Stmt`, `Type` | [§7.5](part_7_narrowing_types_templates_locations.md) | ✗ |
| `hasAnyName` | `NamedDecl` | [§5.2](part_5_narrowing_logic_decls.md) |  |
| `hasAnyOperatorName` | `BinaryOperator`, `CXXOperatorCallExpr`, `CXXRewrittenBinaryOperator`, `UnaryOperator` | [§6.1](part_6_narrowing_stmts.md) |  |
| `hasAnyOverloadedOperatorName` | `CXXOperatorCallExpr`, `FunctionDecl` | [§6.1](part_6_narrowing_stmts.md) |  |
| `hasAnySelector` | `ObjCMessageExpr` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasAttr` | `Decl` | [§5.3](part_5_narrowing_logic_decls.md) |  |
| `hasAutomaticStorageDuration` | `VarDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `hasBitWidth` | `FieldDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `hasCastKind` | `CastExpr` | [§6.4](part_6_narrowing_stmts.md) |  |
| `hasDefaultArgument` | `ParmVarDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `hasDefinition` | `CXXRecordDecl` | [§5.7](part_5_narrowing_logic_decls.md) |  |
| `hasDependentName` | `DependentNameType`, `DependentScopeDeclRefExpr` | [§7.3](part_7_narrowing_types_templates_locations.md) |  |
| `hasDynamicExceptionSpec` | `FunctionDecl`, `FunctionProtoType` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `hasExternalFormalLinkage` | `NamedDecl` | [§5.2](part_5_narrowing_logic_decls.md) |  |
| `hasGlobalStorage` | `VarDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `hasKeywordSelector` | `ObjCMessageExpr` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasLocalQualifiers` | `QualType` | [§7.1](part_7_narrowing_types_templates_locations.md) |  |
| `hasLocalStorage` | `VarDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `hasMemberName` | `CXXDependentScopeMemberExpr` | [§6.5](part_6_narrowing_stmts.md) |  |
| `hasName` | `NamedDecl` | [§5.2](part_5_narrowing_logic_decls.md) |  |
| `hasNullSelector` | `ObjCMessageExpr` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasOperatorName` | `BinaryOperator`, `CXXFoldExpr`, `CXXOperatorCallExpr`, `CXXRewrittenBinaryOperator`, `UnaryOperator` | [§6.1](part_6_narrowing_stmts.md) |  |
| `hasOverloadedOperatorName` | `CXXOperatorCallExpr`, `FunctionDecl` | [§6.1](part_6_narrowing_stmts.md) |  |
| `hasSelector` | `ObjCMessageExpr` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasSize` | `ConstantArrayType`, `StringLiteral` | [§7.2](part_7_narrowing_types_templates_locations.md) |  |
| `hasStaticStorageDuration` | `VarDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `hasThreadStorageDuration` | `VarDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `hasTrailingReturn` | `FunctionDecl` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `hasUnarySelector` | `ObjCMessageExpr` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `isAllowedToContainClauseKind` | `OMPExecutableDirective` | [§11.4](part_11_objc_openmp_cuda_blocks.md) |  |
| `isAnonymous` | `NamespaceDecl` | [§5.3](part_5_narrowing_logic_decls.md) |  |
| `isAnyCharacter` | `QualType` | [§7.1](part_7_narrowing_types_templates_locations.md) |  |
| `isAnyPointer` | `QualType` | [§7.1](part_7_narrowing_types_templates_locations.md) |  |
| `isArray` | `CXXNewExpr` | [§6.3](part_6_narrowing_stmts.md) |  |
| `isArrow` | `CXXDependentScopeMemberExpr`, `MemberExpr`, `UnresolvedMemberExpr` | [§6.5](part_6_narrowing_stmts.md) |  |
| `isAssignmentOperator` | `BinaryOperator`, `CXXOperatorCallExpr`, `CXXRewrittenBinaryOperator` | [§6.1](part_6_narrowing_stmts.md) |  |
| `isAtPosition` | `ParmVarDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `isBaseInitializer` | `CXXCtorInitializer` | [§5.6](part_5_narrowing_logic_decls.md) |  |
| `isBinaryFold` | `CXXFoldExpr` | [§6.1](part_6_narrowing_stmts.md) |  |
| `isBitField` | `FieldDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `isCatchAll` | `CXXCatchStmt` | [§6.6](part_6_narrowing_stmts.md) |  |
| `isClass` | `TagDecl` | [§5.7](part_5_narrowing_logic_decls.md) |  |
| `isClassMessage` | `ObjCMessageExpr` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `isClassMethod` | `ObjCMethodDecl` | [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `isComparisonOperator` | `BinaryOperator`, `CXXOperatorCallExpr`, `CXXRewrittenBinaryOperator` | [§6.1](part_6_narrowing_stmts.md) |  |
| `isConst` | `CXXMethodDecl` | [§5.5](part_5_narrowing_logic_decls.md) |  |
| `isConstQualified` | `QualType` | [§7.1](part_7_narrowing_types_templates_locations.md) |  |
| `isConsteval` | `FunctionDecl`, `IfStmt` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `isConstexpr` | `FunctionDecl`, `IfStmt`, `VarDecl` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `isConstinit` | `VarDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `isCopyAssignmentOperator` | `CXXMethodDecl` | [§5.5](part_5_narrowing_logic_decls.md) |  |
| `isCopyConstructor` | `CXXConstructorDecl` | [§5.6](part_5_narrowing_logic_decls.md) |  |
| `isDefaultConstructor` | `CXXConstructorDecl` | [§5.6](part_5_narrowing_logic_decls.md) |  |
| `isDefaulted` | `FunctionDecl` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `isDefinition` | `FunctionDecl`, `ObjCMethodDecl`, `TagDecl`, `VarDecl` | [§5.4](part_5_narrowing_logic_decls.md), [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `isDelegatingConstructor` | `CXXConstructorDecl` | [§5.6](part_5_narrowing_logic_decls.md) |  |
| `isDeleted` | `FunctionDecl` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `isDerivedFrom` | `CXXRecordDecl`, `ObjCInterfaceDecl` | [§5.7](part_5_narrowing_logic_decls.md), [§8.3](part_8_traversal_tree_decls.md), [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `isDirectlyDerivedFrom` | `CXXRecordDecl`, `ObjCInterfaceDecl` | [§5.7](part_5_narrowing_logic_decls.md), [§8.3](part_8_traversal_tree_decls.md), [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `isEnum` | `TagDecl` | [§5.7](part_5_narrowing_logic_decls.md) |  |
| `isExceptionVariable` | `VarDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `isExpandedFromMacro` | `Decl`, `Stmt`, `TypeLoc` | [§7.4](part_7_narrowing_types_templates_locations.md) |  |
| `isExpansionInFileMatching` | `Decl`, `Stmt`, `TypeLoc` | [§7.4](part_7_narrowing_types_templates_locations.md) |  |
| `isExpansionInMainFile` | `Decl`, `Stmt`, `TypeLoc` | [§7.4](part_7_narrowing_types_templates_locations.md) |  |
| `isExpansionInSystemHeader` | `Decl`, `Stmt`, `TypeLoc` | [§7.4](part_7_narrowing_types_templates_locations.md) |  |
| `isExplicit` | `CXXConstructorDecl`, `CXXConversionDecl`, `CXXDeductionGuideDecl` | [§5.6](part_5_narrowing_logic_decls.md) |  |
| `isExplicitObjectMemberFunction` | `CXXMethodDecl` | [§5.5](part_5_narrowing_logic_decls.md) |  |
| `isExplicitTemplateSpecialization` | `CXXRecordDecl`, `FunctionDecl`, `VarDecl` | [§7.3](part_7_narrowing_types_templates_locations.md) |  |
| `isExternC` | `FunctionDecl`, `VarDecl` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `isFinal` | `CXXMethodDecl`, `CXXRecordDecl` | [§5.5](part_5_narrowing_logic_decls.md) |  |
| `isFirstPrivateKind` | `OMPDefaultClause` | [§11.4](part_11_objc_openmp_cuda_blocks.md) |  |
| `isImplicit` | `Attr`, `Decl`, `InitListExpr`, `LambdaCapture` | [§5.9](part_5_narrowing_logic_decls.md) |  |
| `isInAnonymousNamespace` | `Decl` | [§5.3](part_5_narrowing_logic_decls.md) |  |
| `isInStdNamespace` | `Decl` | [§5.3](part_5_narrowing_logic_decls.md) |  |
| `isInTemplateInstantiation` | `Stmt` | [§7.3](part_7_narrowing_types_templates_locations.md) |  |
| `isInheritingConstructor` | `CXXConstructorDecl` | [§5.6](part_5_narrowing_logic_decls.md) | ✗ |
| `isInitCapture` | `VarDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `isInline` | `FunctionDecl`, `NamespaceDecl`, `VarDecl` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `isInstanceMessage` | `ObjCMessageExpr` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `isInstanceMethod` | `ObjCMethodDecl` | [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `isInstantiated` | `Decl` | [§7.3](part_7_narrowing_types_templates_locations.md) |  |
| `isInstantiationDependent` | `Expr` | [§7.3](part_7_narrowing_types_templates_locations.md) |  |
| `isInteger` | `QualType` | [§7.1](part_7_narrowing_types_templates_locations.md) |  |
| `isIntegral` | `TemplateArgument` | [§7.3](part_7_narrowing_types_templates_locations.md) |  |
| `isLambda` | `CXXRecordDecl` | [§5.7](part_5_narrowing_logic_decls.md) |  |
| `isLeftFold` | `CXXFoldExpr` | [§6.1](part_6_narrowing_stmts.md) |  |
| `isListInitialization` | `CXXConstructExpr` | [§6.3](part_6_narrowing_stmts.md) |  |
| `isMain` | `FunctionDecl` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `isMemberInitializer` | `CXXCtorInitializer` | [§5.6](part_5_narrowing_logic_decls.md) |  |
| `isMoveAssignmentOperator` | `CXXMethodDecl` | [§5.5](part_5_narrowing_logic_decls.md) |  |
| `isMoveConstructor` | `CXXConstructorDecl` | [§5.6](part_5_narrowing_logic_decls.md) |  |
| `isNoReturn` | `FunctionDecl` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `isNoThrow` | `FunctionDecl`, `FunctionProtoType` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `isNoneKind` | `OMPDefaultClause` | [§11.4](part_11_objc_openmp_cuda_blocks.md) |  |
| `isOverride` | `CXXMethodDecl` | [§5.5](part_5_narrowing_logic_decls.md) |  |
| `isPrivate` | `CXXBaseSpecifier`, `Decl` | [§5.3](part_5_narrowing_logic_decls.md) |  |
| `isPrivateKind` | `OMPDefaultClause` | [§11.4](part_11_objc_openmp_cuda_blocks.md) |  |
| `isProtected` | `CXXBaseSpecifier`, `Decl` | [§5.3](part_5_narrowing_logic_decls.md) |  |
| `isPublic` | `CXXBaseSpecifier`, `Decl` | [§5.3](part_5_narrowing_logic_decls.md) |  |
| `isPure` | `CXXMethodDecl` | [§5.5](part_5_narrowing_logic_decls.md) |  |
| `isRightFold` | `CXXFoldExpr` | [§6.1](part_6_narrowing_stmts.md) |  |
| `isSameOrDerivedFrom` | `CXXRecordDecl`, `ObjCInterfaceDecl` | [§5.7](part_5_narrowing_logic_decls.md), [§8.3](part_8_traversal_tree_decls.md), [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `isScoped` | `EnumDecl` | [§5.7](part_5_narrowing_logic_decls.md) |  |
| `isSharedKind` | `OMPDefaultClause` | [§11.4](part_11_objc_openmp_cuda_blocks.md) |  |
| `isSignedInteger` | `QualType` | [§7.1](part_7_narrowing_types_templates_locations.md) |  |
| `isStandaloneDirective` | `OMPExecutableDirective` | [§11.4](part_11_objc_openmp_cuda_blocks.md) |  |
| `isStaticLocal` | `VarDecl` | [§5.8](part_5_narrowing_logic_decls.md) |  |
| `isStaticStorageClass` | `FunctionDecl`, `VarDecl` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `isStruct` | `TagDecl` | [§5.7](part_5_narrowing_logic_decls.md) |  |
| `isTemplateInstantiation` | `CXXRecordDecl`, `FunctionDecl`, `VarDecl` | [§7.3](part_7_narrowing_types_templates_locations.md) |  |
| `isTypeDependent` | `Expr` | [§7.3](part_7_narrowing_types_templates_locations.md) |  |
| `isUnaryFold` | `CXXFoldExpr` | [§6.1](part_6_narrowing_stmts.md) |  |
| `isUnion` | `TagDecl` | [§5.7](part_5_narrowing_logic_decls.md) |  |
| `isUnsignedInteger` | `QualType` | [§7.1](part_7_narrowing_types_templates_locations.md) |  |
| `isUserProvided` | `CXXMethodDecl` | [§5.5](part_5_narrowing_logic_decls.md) |  |
| `isValueDependent` | `Expr` | [§7.3](part_7_narrowing_types_templates_locations.md) |  |
| `isVariadic` | `FunctionDecl` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `isVirtual` | `CXXBaseSpecifier`, `CXXMethodDecl` | [§5.5](part_5_narrowing_logic_decls.md) |  |
| `isVirtualAsWritten` | `CXXMethodDecl` | [§5.5](part_5_narrowing_logic_decls.md) |  |
| `isVolatileQualified` | `QualType` | [§7.1](part_7_narrowing_types_templates_locations.md) |  |
| `isWeak` | `FunctionDecl` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `isWritten` | `CXXCtorInitializer` | [§5.6](part_5_narrowing_logic_decls.md) |  |
| `mapAnyOf` | `*`, `unspecified` | [§5.1](part_5_narrowing_logic_decls.md) |  |
| `matchesName` | `NamedDecl` | [§5.2](part_5_narrowing_logic_decls.md) |  |
| `matchesSelector` | `ObjCMessageExpr` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `memberHasSameNameAsBoundNode` | `CXXDependentScopeMemberExpr` | [§6.5](part_6_narrowing_stmts.md) |  |
| `nullPointerConstant` | `Expr` | [§6.2](part_6_narrowing_stmts.md) |  |
| `numSelectorArgs` | `ObjCMessageExpr` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `ofKind` | `UnaryExprOrTypeTraitExpr` | [§6.8](part_6_narrowing_stmts.md) |  |
| `parameterCountIs` | `FunctionDecl`, `FunctionProtoType` | [§5.4](part_5_narrowing_logic_decls.md) |  |
| `realFloatingPointType` | `Type` | [§7.1](part_7_narrowing_types_templates_locations.md) |  |
| `requiresZeroInitialization` | `CXXConstructExpr` | [§6.3](part_6_narrowing_stmts.md) |  |
| `statementCountIs` | `CompoundStmt` | [§6.6](part_6_narrowing_stmts.md) |  |
| `templateArgumentCountIs` | `ClassTemplateSpecializationDecl`, `FunctionDecl`, `TemplateSpecializationType`, `VarTemplateSpecializationDecl` | [§7.3](part_7_narrowing_types_templates_locations.md) |  |
| `templateArgumentLocCountIs` | `ClassTemplateSpecializationDecl`, `DeclRefExpr`, `FunctionDecl`, `OverloadExpr`, `TemplateSpecializationTypeLoc`, `VarTemplateSpecializationDecl` | [§7.3](part_7_narrowing_types_templates_locations.md) | ✗ |
| `unless` | `*` | [§5.1](part_5_narrowing_logic_decls.md) |  |
| `usesADL` | `CallExpr` | [§6.3](part_6_narrowing_stmts.md) |  |
| `voidType` | `Type` | [§7.1](part_7_narrowing_types_templates_locations.md) |  |

## Traversal matchers (141)

| Matcher | Returns | Where | |
|---|---|---|---|
| `alignOfExpr` | `Stmt` | [§9.9](part_9_traversal_stmts.md) |  |
| `binaryOperation` | `*` | [§8.1](part_8_traversal_tree_decls.md) |  |
| `callee` | `CXXFoldExpr`, `CallExpr`, `ObjCMessageExpr` | [§9.1](part_9_traversal_stmts.md), [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `capturesVar` | `LambdaCapture` | [§9.8](part_9_traversal_stmts.md) |  |
| `containsDeclaration` | `DeclStmt` | [§9.4](part_9_traversal_stmts.md) |  |
| `eachOf` | `*` | [§8.1](part_8_traversal_tree_decls.md) |  |
| `findAll` | `*` | [§8.1](part_8_traversal_tree_decls.md) | ✗ |
| `forCallable` | `Stmt` | [§9.4](part_9_traversal_stmts.md) |  |
| `forDecomposition` | `BindingDecl` | [§8.5](part_8_traversal_tree_decls.md) |  |
| `forEach` | `*` | [§8.1](part_8_traversal_tree_decls.md) |  |
| `forEachArgumentWithParam` | `CXXConstructExpr`, `CallExpr` | [§9.1](part_9_traversal_stmts.md) |  |
| `forEachArgumentWithParamType` | `CXXConstructExpr`, `CallExpr` | [§9.1](part_9_traversal_stmts.md) |  |
| `forEachConstructorInitializer` | `CXXConstructorDecl` | [§8.4](part_8_traversal_tree_decls.md) |  |
| `forEachDescendant` | `*` | [§8.1](part_8_traversal_tree_decls.md) |  |
| `forEachLambdaCapture` | `LambdaExpr` | [§9.8](part_9_traversal_stmts.md) |  |
| `forEachOverridden` | `CXXMethodDecl` | [§8.3](part_8_traversal_tree_decls.md) |  |
| `forEachSwitchCase` | `SwitchStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `forEachTemplateArgument` | `ClassTemplateSpecializationDecl`, `FunctionDecl`, `TemplateSpecializationType`, `VarTemplateSpecializationDecl` | [§10.6](part_10_traversal_types_templates.md) |  |
| `forField` | `CXXCtorInitializer` | [§8.4](part_8_traversal_tree_decls.md) |  |
| `forFunction` | `Stmt` | [§9.4](part_9_traversal_stmts.md) |  |
| `has` | `*` | [§8.1](part_8_traversal_tree_decls.md) |  |
| `hasAncestor` | `*` | [§8.1](part_8_traversal_tree_decls.md) |  |
| `hasAnyArgument` | `CXXConstructExpr`, `CXXUnresolvedConstructExpr`, `CallExpr`, `ObjCMessageExpr` | [§9.1](part_9_traversal_stmts.md), [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasAnyBase` | `CXXRecordDecl` | [§8.3](part_8_traversal_tree_decls.md) |  |
| `hasAnyBinding` | `DecompositionDecl` | [§8.5](part_8_traversal_tree_decls.md) |  |
| `hasAnyBody` | `FunctionDecl` | [§8.2](part_8_traversal_tree_decls.md) |  |
| `hasAnyCapture` | `LambdaExpr` | [§9.8](part_9_traversal_stmts.md) |  |
| `hasAnyClause` | `OMPExecutableDirective` | [§11.4](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasAnyConstructorInitializer` | `CXXConstructorDecl` | [§8.4](part_8_traversal_tree_decls.md) |  |
| `hasAnyDeclaration` | `OverloadExpr` | [§9.1](part_9_traversal_stmts.md) |  |
| `hasAnyParameter` | `BlockDecl`, `FunctionDecl`, `ObjCMethodDecl` | [§8.2](part_8_traversal_tree_decls.md), [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasAnyPlacementArg` | `CXXNewExpr` | [§9.7](part_9_traversal_stmts.md) |  |
| `hasAnySubstatement` | `CompoundStmt`, `StmtExpr` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasAnyTemplateArgument` | `ClassTemplateSpecializationDecl`, `FunctionDecl`, `TemplateSpecializationType`, `VarTemplateSpecializationDecl` | [§10.6](part_10_traversal_types_templates.md) |  |
| `hasAnyTemplateArgumentLoc` | `ClassTemplateSpecializationDecl`, `DeclRefExpr`, `FunctionDecl`, `OverloadExpr`, `TemplateSpecializationTypeLoc`, `VarTemplateSpecializationDecl` | [§10.4](part_10_traversal_types_templates.md) |  |
| `hasAnyUsingShadowDecl` | `BaseUsingDecl` | [§8.6](part_8_traversal_tree_decls.md) |  |
| `hasArgument` | `CXXConstructExpr`, `CXXUnresolvedConstructExpr`, `CallExpr`, `ObjCMessageExpr` | [§9.1](part_9_traversal_stmts.md), [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasArgumentOfType` | `UnaryExprOrTypeTraitExpr` | [§9.9](part_9_traversal_stmts.md) |  |
| `hasArraySize` | `CXXNewExpr` | [§9.7](part_9_traversal_stmts.md) |  |
| `hasBase` | `ArraySubscriptExpr` | [§9.2](part_9_traversal_stmts.md) |  |
| `hasBinding` | `DecompositionDecl` | [§8.5](part_8_traversal_tree_decls.md) |  |
| `hasBody` | `CXXForRangeStmt`, `CoroutineBodyStmt`, `DoStmt`, `ForStmt`, `FunctionDecl`, `WhileStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasCanonicalType` | `QualType` | [§10.1](part_10_traversal_types_templates.md) |  |
| `hasCaseConstant` | `CaseStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasCondition` | `AbstractConditionalOperator`, `DoStmt`, `ForStmt`, `IfStmt`, `SwitchStmt`, `WhileStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasConditionVariableStatement` | `ForStmt`, `IfStmt`, `SwitchStmt`, `WhileStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasDecayedType` | `DecayedType` | [§10.3](part_10_traversal_types_templates.md) |  |
| `hasDeclContext` | `Decl` | [§8.6](part_8_traversal_tree_decls.md) |  |
| `hasDeclaration` | `AddrLabelExpr`, `CXXConstructExpr`, `CXXNewExpr`, `CallExpr`, `DeclRefExpr`, `EnumType`, `InjectedClassNameType`, `LabelStmt`, `MemberExpr`, `QualType`, `RecordType`, `TagType`, `TemplateSpecializationType`, `TemplateTypeParmType`, `TypedefType`, `UnresolvedUsingType`, `UsingType` | [§10.2](part_10_traversal_types_templates.md) |  |
| `hasDeducedType` | `AutoType` | [§10.3](part_10_traversal_types_templates.md) |  |
| `hasDescendant` | `*` | [§8.1](part_8_traversal_tree_decls.md) |  |
| `hasDestinationType` | `ExplicitCastExpr` | [§10.4](part_10_traversal_types_templates.md) |  |
| `hasDirectBase` | `CXXRecordDecl` | [§8.3](part_8_traversal_tree_decls.md) |  |
| `hasEitherOperand` | `BinaryOperator`, `CXXFoldExpr`, `CXXOperatorCallExpr`, `CXXRewrittenBinaryOperator` | [§9.2](part_9_traversal_stmts.md) |  |
| `hasElementType` | `ArrayType`, `ComplexType` | [§10.3](part_10_traversal_types_templates.md) |  |
| `hasElse` | `IfStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasExplicitSpecifier` | `FunctionDecl` | [§8.2](part_8_traversal_tree_decls.md) |  |
| `hasFalseExpression` | `AbstractConditionalOperator` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasFoldInit` | `CXXFoldExpr` | [§9.2](part_9_traversal_stmts.md) |  |
| `hasImplicitDestinationType` | `ImplicitCastExpr` | [§10.4](part_10_traversal_types_templates.md) |  |
| `hasInClassInitializer` | `FieldDecl` | [§8.5](part_8_traversal_tree_decls.md) |  |
| `hasIncrement` | `ForStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasIndex` | `ArraySubscriptExpr` | [§9.2](part_9_traversal_stmts.md) |  |
| `hasInit` | `InitListExpr` | [§9.7](part_9_traversal_stmts.md) |  |
| `hasInitStatement` | `CXXForRangeStmt`, `IfStmt`, `SwitchStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasInitializer` | `VarDecl` | [§8.5](part_8_traversal_tree_decls.md) |  |
| `hasLHS` | `ArraySubscriptExpr`, `BinaryOperator`, `CXXFoldExpr`, `CXXOperatorCallExpr`, `CXXRewrittenBinaryOperator` | [§9.2](part_9_traversal_stmts.md) |  |
| `hasLoopInit` | `ForStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasLoopVariable` | `CXXForRangeStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasMethod` | `CXXRecordDecl` | [§8.3](part_8_traversal_tree_decls.md) |  |
| `hasObjectExpression` | `CXXDependentScopeMemberExpr`, `MemberExpr`, `UnresolvedMemberExpr` | [§9.4](part_9_traversal_stmts.md) |  |
| `hasOperands` | `BinaryOperator`, `CXXFoldExpr`, `CXXOperatorCallExpr`, `CXXRewrittenBinaryOperator` | [§9.2](part_9_traversal_stmts.md) |  |
| `hasParameter` | `BlockDecl`, `FunctionDecl`, `ObjCMethodDecl` | [§8.2](part_8_traversal_tree_decls.md), [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasParent` | `*` | [§8.1](part_8_traversal_tree_decls.md) |  |
| `hasPattern` | `CXXFoldExpr` | [§9.2](part_9_traversal_stmts.md) |  |
| `hasPlacementArg` | `CXXNewExpr` | [§9.7](part_9_traversal_stmts.md) |  |
| `hasPointeeLoc` | `PointerTypeLoc` | [§10.4](part_10_traversal_types_templates.md) |  |
| `hasPrefix` | `NestedNameSpecifier`, `NestedNameSpecifierLoc` | [§10.5](part_10_traversal_types_templates.md) |  |
| `hasQualifier` | `Type` | [§10.3](part_10_traversal_types_templates.md) |  |
| `hasRHS` | `ArraySubscriptExpr`, `BinaryOperator`, `CXXFoldExpr`, `CXXOperatorCallExpr`, `CXXRewrittenBinaryOperator` | [§9.2](part_9_traversal_stmts.md) |  |
| `hasRangeInit` | `CXXForRangeStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasReceiver` | `ObjCMessageExpr` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasReceiverType` | `ObjCMessageExpr` | [§11.3](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasReferentLoc` | `ReferenceTypeLoc` | [§10.4](part_10_traversal_types_templates.md) |  |
| `hasReplacementType` | `SubstTemplateTypeParmType` | [§10.3](part_10_traversal_types_templates.md) |  |
| `hasReturnTypeLoc` | `FunctionDecl` | [§10.4](part_10_traversal_types_templates.md) |  |
| `hasReturnValue` | `ReturnStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasSingleDecl` | `DeclStmt` | [§9.4](part_9_traversal_stmts.md) |  |
| `hasSizeExpr` | `VariableArrayType` | [§10.3](part_10_traversal_types_templates.md) |  |
| `hasSourceExpression` | `CastExpr`, `OpaqueValueExpr` | [§9.6](part_9_traversal_stmts.md) |  |
| `hasSpecializedTemplate` | `ClassTemplateSpecializationDecl` | [§10.6](part_10_traversal_types_templates.md) |  |
| `hasStructuredBlock` | `OMPExecutableDirective` | [§11.4](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasSyntacticForm` | `InitListExpr` | [§9.7](part_9_traversal_stmts.md) |  |
| `hasTargetDecl` | `UsingShadowDecl` | [§8.6](part_8_traversal_tree_decls.md) |  |
| `hasTemplateArgument` | `ClassTemplateSpecializationDecl`, `FunctionDecl`, `TemplateSpecializationType`, `VarTemplateSpecializationDecl` | [§10.6](part_10_traversal_types_templates.md) |  |
| `hasTemplateArgumentLoc` | `ClassTemplateSpecializationDecl`, `DeclRefExpr`, `FunctionDecl`, `OverloadExpr`, `TemplateSpecializationTypeLoc`, `VarTemplateSpecializationDecl` | [§10.4](part_10_traversal_types_templates.md) |  |
| `hasThen` | `IfStmt` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasTrueExpression` | `AbstractConditionalOperator` | [§9.3](part_9_traversal_stmts.md) |  |
| `hasType` | `CXXBaseSpecifier`, `Expr`, `FriendDecl`, `ObjCInterfaceDecl`, `TypedefNameDecl`, `ValueDecl` | [§10.1](part_10_traversal_types_templates.md), [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasTypeLoc` | `BlockDecl`, `CXXBaseSpecifier`, `CXXCtorInitializer`, `CXXFunctionalCastExpr`, `CXXNewExpr`, `CXXTemporaryObjectExpr`, `CXXUnresolvedConstructExpr`, `CompoundLiteralExpr`, `DeclaratorDecl`, `ExplicitCastExpr`, `ObjCPropertyDecl`, `TemplateArgumentLoc`, `TypedefNameDecl` | [§10.4](part_10_traversal_types_templates.md), [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `hasUnaryOperand` | `CXXOperatorCallExpr`, `UnaryOperator` | [§9.2](part_9_traversal_stmts.md) |  |
| `hasUnderlyingDecl` | `NamedDecl` | [§8.6](part_8_traversal_tree_decls.md) |  |
| `hasUnderlyingType` | `Type` | [§10.3](part_10_traversal_types_templates.md) |  |
| `hasUnqualifiedDesugaredType` | `Type` | [§10.1](part_10_traversal_types_templates.md) |  |
| `hasUnqualifiedLoc` | `QualifiedTypeLoc` | [§10.4](part_10_traversal_types_templates.md) |  |
| `hasValueType` | `AtomicType` | [§10.3](part_10_traversal_types_templates.md) |  |
| `ignoringElidableConstructorCall` | `Expr` | [§9.5](part_9_traversal_stmts.md) |  |
| `ignoringImpCasts` | `Expr` | [§9.5](part_9_traversal_stmts.md) |  |
| `ignoringImplicit` | `Expr` | [§9.5](part_9_traversal_stmts.md) |  |
| `ignoringParenCasts` | `Expr` | [§9.5](part_9_traversal_stmts.md) |  |
| `ignoringParenImpCasts` | `Expr` | [§9.5](part_9_traversal_stmts.md) |  |
| `ignoringParens` | `Expr`, `QualType` | [§9.5](part_9_traversal_stmts.md), [§10.3](part_10_traversal_types_templates.md) |  |
| `innerType` | `ParenType` | [§10.3](part_10_traversal_types_templates.md) |  |
| `invocation` | `*` | [§8.1](part_8_traversal_tree_decls.md) |  |
| `isDerivedFrom` | `CXXRecordDecl`, `ObjCInterfaceDecl` | [§5.7](part_5_narrowing_logic_decls.md), [§8.3](part_8_traversal_tree_decls.md), [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `isDirectlyDerivedFrom` | `CXXRecordDecl`, `ObjCInterfaceDecl` | [§5.7](part_5_narrowing_logic_decls.md), [§8.3](part_8_traversal_tree_decls.md), [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `isExpr` | `TemplateArgument` | [§10.6](part_10_traversal_types_templates.md) |  |
| `isSameOrDerivedFrom` | `CXXRecordDecl`, `ObjCInterfaceDecl` | [§5.7](part_5_narrowing_logic_decls.md), [§8.3](part_8_traversal_tree_decls.md), [§11.2](part_11_objc_openmp_cuda_blocks.md) |  |
| `loc` | `NestedNameSpecifierLoc`, `TypeLoc` | [§10.4](part_10_traversal_types_templates.md) |  |
| `member` | `MemberExpr` | [§9.4](part_9_traversal_stmts.md) |  |
| `ofClass` | `CXXMethodDecl` | [§8.3](part_8_traversal_tree_decls.md) |  |
| `on` | `CXXMemberCallExpr` | [§9.1](part_9_traversal_stmts.md) |  |
| `onImplicitObjectArgument` | `CXXMemberCallExpr` | [§9.1](part_9_traversal_stmts.md) |  |
| `optionally` | `*` | [§8.1](part_8_traversal_tree_decls.md) |  |
| `pointee` | `BlockPointerType`, `MemberPointerType`, `ObjCObjectPointerType`, `PointerType`, `ReferenceType` | [§10.3](part_10_traversal_types_templates.md), [§11.6](part_11_objc_openmp_cuda_blocks.md) |  |
| `pointsTo` | `QualType` | [§10.3](part_10_traversal_types_templates.md) |  |
| `references` | `QualType` | [§10.3](part_10_traversal_types_templates.md) |  |
| `refersToDeclaration` | `TemplateArgument` | [§10.6](part_10_traversal_types_templates.md) |  |
| `refersToIntegralType` | `TemplateArgument` | [§10.6](part_10_traversal_types_templates.md) |  |
| `refersToTemplate` | `TemplateArgument` | [§10.6](part_10_traversal_types_templates.md) |  |
| `refersToType` | `TemplateArgument` | [§10.6](part_10_traversal_types_templates.md) |  |
| `returns` | `FunctionDecl` | [§10.4](part_10_traversal_types_templates.md) |  |
| `sizeOfExpr` | `Stmt` | [§9.9](part_9_traversal_stmts.md) |  |
| `specifiesNamespace` | `NestedNameSpecifier` | [§10.5](part_10_traversal_types_templates.md) |  |
| `specifiesType` | `NestedNameSpecifier` | [§10.5](part_10_traversal_types_templates.md) |  |
| `specifiesTypeLoc` | `NestedNameSpecifierLoc` | [§10.5](part_10_traversal_types_templates.md) |  |
| `thisPointerType` | `CXXMemberCallExpr` | [§9.1](part_9_traversal_stmts.md) |  |
| `throughUsingDecl` | `DeclRefExpr`, `UsingType` | [§10.3](part_10_traversal_types_templates.md) |  |
| `to` | `DeclRefExpr` | [§9.4](part_9_traversal_stmts.md) |  |
| `traverse` | `*` | [§8.1](part_8_traversal_tree_decls.md) | ✗ |
| `withInitializer` | `CXXCtorInitializer` | [§8.4](part_8_traversal_tree_decls.md) |  |
