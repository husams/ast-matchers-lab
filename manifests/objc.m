// Objective-C sample for Part 11 — no imports, so the runtime scaffolding
// is declared by hand. Each declaration is here so that a matcher in the
// docs has something to hit.

typedef signed char BOOL;
typedef unsigned long NSUInteger;

// Root class: the attribute silences -Wobjc-root-class.
__attribute__((objc_root_class))
@interface NSObject {
  void *isa;
}
+ (id)alloc;
- (id)init;
- (void)release;
@end

@implementation NSObject
+ (id)alloc { return (id)0; }
- (id)init { return self; }
- (void)release {}
@end

// @"..." literals have type NSString *, so the class must exist; no ivars or
// methods are needed for the parse.
@interface NSString : NSObject
@end

@protocol FooDelegate
- (void)fooDidFinish:(id)foo;
@end

@protocol Loggable
- (void)log;
@end

@interface Foo : NSObject <Loggable> {
  BOOL _enabled;
  NSString *_name;
}
@property BOOL enabled;
@property (readonly) NSString *name;
+ (instancetype)fooWithName:(NSString *)name;
- (void)method;
- (void)setName:(NSString *)name enabled:(BOOL)flag;
- (NSUInteger)countFrom:(NSUInteger)start to:(NSUInteger)end;
- (void)log;
@end

@implementation Foo
@synthesize enabled = _enabled;
@synthesize name = _name;

+ (instancetype)fooWithName:(NSString *)name {
  Foo *f = [[Foo alloc] init];
  [f setName:name enabled:1];
  return f;
}
- (void)method {
  _enabled = 1;
  _name = @"default";
}
- (void)setName:(NSString *)name enabled:(BOOL)flag {
  _name = name;
  _enabled = flag;
}
- (NSUInteger)countFrom:(NSUInteger)start to:(NSUInteger)end {
  return end - start;
}
- (void)log {}
@end

@interface Foo (Additions)
- (void)extra;
@end

@implementation Foo (Additions)
- (void)extra { [self method]; }
@end

@interface Bar : Foo <FooDelegate>
- (void)fooDidFinish:(id)foo;
@end

@implementation Bar
- (void)fooDidFinish:(id)foo { [foo release]; }
@end

@interface Baz : Bar
@end

@implementation Baz
@end

void useIt(Foo *foo, Bar *bar) {
  Baz *baz = [[Baz alloc] init];
  [foo method];
  [bar setName:@"bar" enabled:0];
  NSUInteger n = [foo countFrom:1 to:10];
  (void)n;
  (void)*foo;
  [Foo fooWithName:@"fresh"];
  @autoreleasepool {
    int x = 0;
    (void)x;
    [baz log];
  }
  @try {
    [foo extra];
  } @catch (Foo *e) {
    @throw e;
  } @finally {
    [foo release];
  }
}
